"""`daoc dev e2e`: step sequencing with stubbed server and client, the lock,
the port move and its revert, and the evidence bundle.

The server install is a tree of sh stubs; the client side (install, launch,
process lookup, teardown) is patched in-process, and a fake clock replaces
every wait. Nothing real is launched or signalled.
"""
import os
import subprocess
import tempfile
import time as real_time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import e2e
from daoc_cli.errors import DaocError

ACCOUNT = "probeacct"
PASSWORD = "s3cret-pw"
REAL_LAUNCH = e2e._launch

CONFIG = """<Server>
  <Port>10300</Port>
  <RegionPort>10400</RegionPort>
  <UdpPort>10400</UdpPort>
</Server>
"""

SERVER_SH = """#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
echo "$*" >> "$here/script-calls.log"
case "$1" in
  start)
    cp config/serverconfig.xml config-at-start.xml
    [ -f "$here/no-listen" ] || echo "Server is now listening"
    ;;
  stop)
    [ -f "$here/fail-stop" ] && exit 1
    ;;
esac
exit 0
"""

ADMIN = """#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
[ -f "$here/admin-fail" ] && { echo "error: database locked"; exit 1; }
case "$2" in
  create) echo "player, $3 created" ;;
  show) echo "$3 last login 2026-10-11 12:00" ;;
esac
"""


def _exe(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class FakeTime:
    """monotonic/sleep on a virtual clock, so 10 x 180 s windows take no time."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def time(self):
        return 1_800_000_000.0

    def strftime(self, fmt):
        return real_time.strftime(fmt)


class E2ETest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = make_checkout(self.tmp)
        self.sd = self.root / "server" / "dist" / "daoc-server"
        _exe(self.sd / "bin" / "CoreServer", "#!/bin/sh\n")
        _exe(self.sd / "daoc-server.sh", SERVER_SH)
        _exe(self.sd / "daoc-admin", ADMIN)
        (self.sd / "defaults").mkdir()
        (self.sd / "defaults" / "serverconfig.xml").write_text(CONFIG)
        (self.sd / "defaults" / "world.sqlite").write_text("world")
        self.server_log = self.sd / "logs" / "server.log"
        self.server_log.parent.mkdir()
        self.server_log.write_text("old line: User probeacct logging on!\n")
        game_dll = self.root / "dist" / "OfflineDAoC" / "runtime" / "client-opendaoc" / "app" / "game.dll"
        game_dll.parent.mkdir(parents=True)
        game_dll.write_bytes(b"MZ")
        self.wine_log = self.tmp / "daoc-wine.log"

        # Client behaviour per launch: a list of "login", "wrong", "crash" or "none".
        self.plan = ["login"]
        self.launches = 0
        self.pid_calls = 0
        self.server_install = mock.Mock()
        self.client_install = mock.Mock()
        self.kill = mock.Mock()
        patches = [
            mock.patch.object(e2e.server, "install", self.server_install),
            mock.patch.object(e2e.client, "install", self.client_install),
            mock.patch.object(e2e.client_runtime, "kill", self.kill),
            mock.patch.object(e2e.client_runtime, "game_pids", self._game_pids),
            mock.patch.object(e2e, "_start_detached", self._start_detached),
            mock.patch.object(e2e, "_launch", self._launch),
            mock.patch.object(e2e, "_port_open", lambda port: port == 20300),
            mock.patch.object(e2e, "_alive", lambda pid: pid == 4242),
            mock.patch.object(e2e, "WINE_LOG", self.wine_log),
            mock.patch.object(e2e, "time", FakeTime()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _start_detached(argv, cwd, log):
        """Run the server stub in the foreground so console.out is complete."""
        with open(log, "wb") as out:
            subprocess.run([str(a) for a in argv], cwd=str(cwd), stdout=out,
                           stderr=subprocess.STDOUT, check=True)

    def _launch(self, checkout, account, password):
        self.assertEqual((account, password), (ACCOUNT, PASSWORD))
        self.launches += 1
        self.pid_calls = 0
        self.wine_log.write_text(f"wine output for launch {self.launches}\n")
        kind = self.plan[min(self.launches, len(self.plan)) - 1]
        line = {"login": f"LoginRequestHandler: User {ACCOUNT} logging on!\n",
                "wrong": f"LoginRequestHandler: User {ACCOUNT} logging on!\nWrong password!\n"}.get(kind)
        if line:
            with self.server_log.open("a") as f:
                f.write(line)

    def _game_pids(self, checkout):
        kind = self.plan[min(self.launches, len(self.plan)) - 1] if self.launches else "none"
        self.pid_calls += 1
        if kind == "login":
            return [4242]
        if kind == "crash":
            # Seen, then gone (the death), then the snapshot's lookup: this test
            # process stands in so /bin/ps has a real pid to describe.
            return {1: [1111], 3: [os.getpid()]}.get(self.pid_calls, [])
        return []

    def run_e2e(self):
        return run_cli(["dev", "e2e", ACCOUNT, PASSWORD], self.root)

    def script_calls(self):
        return (self.sd / "script-calls.log").read_text().splitlines()

    def assert_restored(self):
        config = self.sd / "config" / "serverconfig.xml"
        if config.exists():
            self.assertEqual(config.read_text(), CONFIG)
        self.assertFalse((self.sd / "config" / "serverconfig.xml.bak").exists())
        self.assertFalse((self.root / ".e2e.lock").exists())

    def assert_failed_at(self, step, code, err):
        self.assertEqual(code, 1, err)
        self.assertIn(f"E2E FAILED at: {step}", err)
        self.assert_restored()

    def new_client(self, login=True, pids=(4242,), port_busy=False):
        """Patch the new-client side: its install, launch and process lookup."""
        self.booted = False
        self.new_launches = []
        boot = self._start_detached

        def start(argv, cwd, log):
            boot(argv, cwd, log)
            self.booted = True

        def launch(checkout, account, password):
            self.new_launches.append((account, password))
            if login:
                with self.server_log.open("a") as f:
                    f.write(f"LoginRequestHandler: User {ACCOUNT} logging on!\n")

        self.new_install = mock.Mock()
        for p in (mock.patch.object(e2e, "_start_detached", start),
                  mock.patch.object(e2e, "_launch_new", launch),
                  mock.patch.object(e2e, "_port_open",
                                    lambda port: port == 10300 and (self.booted or port_busy)),
                  mock.patch.object(e2e.client_runtime, "new_pids", lambda co: list(pids)),
                  mock.patch.object(e2e.newclient, "install", self.new_install)):
            p.start()
            self.addCleanup(p.stop)

    def test_new_uses_10300(self):
        self.new_client()
        code, out, err = run_cli(["dev", "e2e", ACCOUNT, PASSWORD, "--client", "new"], self.root)
        self.assertEqual(code, 0, err)
        self.assertIn("E2E: PASS", out)
        self.assertIn("<Port>10300</Port>", (self.sd / "config-at-start.xml").read_text())
        self.assertEqual(self.new_launches, [(ACCOUNT, PASSWORD)])
        self.new_install.assert_called_once()
        self.client_install.assert_not_called()
        self.assert_restored()

    def test_new_refuses_busy_port(self):
        self.new_client(port_busy=True)
        code, out, err = run_cli(["dev", "e2e", ACCOUNT, PASSWORD, "--client", "new"], self.root)
        self.assertEqual(code, 2)
        self.assertIn("10300", err)
        self.assertFalse((self.sd / "script-calls.log").exists())
        self.assertEqual(self.new_launches, [])

    def test_new_alive_check_uses_new_pids(self):
        self.new_client(pids=())
        code, out, err = run_cli(["dev", "e2e", ACCOUNT, PASSWORD, "--client", "new"], self.root)
        self.assertEqual(code, 1)
        self.assertIn("could not find the client process", err)

    def test_fresh_save_follows_the_edition(self):
        (self.sd / "defaults" / "world-sluaghbinder.sqlite").write_text("sluaghbinder world")
        (self.sd / "config").mkdir()
        (self.sd / "config" / "edition").write_text("sluaghbinder\n")
        code, out, err = self.run_e2e()
        self.assertEqual(code, 0, err)
        self.assertEqual((self.sd / "data" / "opendaoc.sqlite3.db").read_text(), "sluaghbinder world")

    def test_boot_refuses_a_config_port_the_client_will_not_use(self):
        # A config left on another port would send the client to a port nothing listens on.
        (self.sd / "config").mkdir()
        (self.sd / "config" / "serverconfig.xml").write_text(CONFIG.replace("10300", "20301"))
        code, out, err = self.run_e2e()
        self.assertEqual(code, 1)
        self.assertIn("<Port>20301</Port>", err)
        self.assertIn("20300", err)
        self.assertEqual(self.launches, 0)

    def test_pass_moves_ports_reverts_them_and_writes_the_evidence(self):
        (self.root / "evidence").mkdir()
        (self.root / "evidence" / "wine-attempt-7.log").write_text("stale")
        code, out, err = self.run_e2e()
        self.assertEqual(code, 0, err)
        self.assertIn("E2E: PASS", out)
        self.assertNotIn(PASSWORD, out + err)
        at_start = (self.sd / "config-at-start.xml").read_text()
        self.assertIn("<Port>20300</Port>", at_start)
        self.assertIn("<RegionPort>20400</RegionPort>", at_start)
        self.assertIn("<UdpPort>20400</UdpPort>", at_start)
        self.assert_restored()
        self.assertEqual((self.sd / "data" / "opendaoc.sqlite3.db").read_text(), "world")
        self.assertEqual(self.script_calls(), ["stop", "start --console", "stop", "stop"])
        evidence = self.root / "evidence"
        self.assertEqual(sorted(p.name for p in evidence.iterdir()), [
            "account-show.txt", "account.txt", "launch-attempts.txt", "server-boot.log",
            "server.log", "wine.log"])
        self.assertEqual((evidence / "launch-attempts.txt").read_text(), "1\n")
        self.assertIn("Server is now listening", (evidence / "server-boot.log").read_text())
        self.server_install.assert_not_called()
        self.client_install.assert_not_called()

    def test_crashed_attempt_keeps_its_wine_log_and_a_pid_comm_snapshot(self):
        self.plan = ["crash", "login"]
        with mock.patch.object(e2e.proc, "run", wraps=e2e.proc.run) as run:
            code, out, err = self.run_e2e()
        self.assertEqual(code, 0, err)
        self.assertIn("client process died before login", out)
        evidence = self.root / "evidence"
        self.assertEqual((evidence / "wine-attempt-1.log").read_text(), "wine output for launch 1\n")
        snapshot = (evidence / "pgrep-at-attempt-1.txt").read_text().splitlines()
        self.assertRegex(snapshot[0], r"^\d\d:\d\d:\d\d$")
        self.assertEqual(snapshot[1].split()[0], str(os.getpid()))
        self.assertEqual((evidence / "launch-attempts.txt").read_text(), "2\n")
        ps_calls = [c.args[0] for c in run.call_args_list if c.args[0][0] == e2e.client_runtime.PS]
        self.assertEqual(ps_calls, [[e2e.client_runtime.PS, "-o", "pid=,comm=", "-p",
                                     str(os.getpid())]])

    def test_missing_installs_run_in_process(self):
        (self.sd / "bin" / "CoreServer").unlink()
        game_dll = self.root / "dist" / "OfflineDAoC" / "runtime" / "client-opendaoc" / "app" / "game.dll"
        game_dll.unlink()
        client_root = self.root / "dist" / "OfflineDAoC"
        for d in sorted(client_root.rglob("*"), reverse=True):
            d.rmdir()
        client_root.rmdir()

        def install_client(checkout):
            game_dll.parent.mkdir(parents=True)
            game_dll.write_bytes(b"MZ")

        self.client_install.side_effect = install_client
        code, _, err = self.run_e2e()
        self.assertEqual(code, 0, err)
        self.server_install.assert_called_once()
        self.client_install.assert_called_once()

    def test_server_install_failure(self):
        (self.sd / "bin" / "CoreServer").unlink()
        self.server_install.side_effect = DaocError("build failed")
        code, _, err = self.run_e2e()
        self.assert_failed_at("server install", code, err)
        self.assertIn("build failed", err)
        self.client_install.assert_not_called()
        self.assertEqual(self.launches, 0)

    def test_server_never_listening(self):
        (self.sd / "no-listen").write_text("")
        code, _, err = self.run_e2e()
        self.assert_failed_at("server boot (alternate ports 20300/20400)", code, err)
        self.assertIn("never reached 'listening' within 120 s", err)
        self.assertEqual(self.launches, 0)
        self.assertEqual(self.script_calls()[-1], "stop")

    def test_account_creation_failure(self):
        (self.sd / "admin-fail").write_text("")
        code, _, err = self.run_e2e()
        self.assert_failed_at("account creation", code, err)
        self.assertIn("database locked", (self.root / "evidence" / "account.txt").read_text())
        self.assertEqual(self.launches, 0)

    def test_client_install_failure(self):
        for p in sorted((self.root / "dist").rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
        self.client_install.side_effect = DaocError("download failed")
        code, _, err = self.run_e2e()
        self.assert_failed_at("client install", code, err)
        self.assertIn("game.dll missing after client install", err)
        self.assertEqual(self.launches, 0)

    def test_no_login_after_ten_attempts(self):
        self.plan = ["none"]
        code, out, err = self.run_e2e()
        self.assert_failed_at("client launch", code, err)
        self.assertEqual(self.launches, 10)
        self.assertIn(f"no 'User {ACCOUNT} logging on!'", err)
        self.assertEqual((self.root / "evidence" / "launch-attempts.txt").read_text(), "10\n")
        # The run still shuts the server down and reports.
        self.assertIn("=== server shutdown ===", out)
        self.assertIn("E2E: FAIL", out)

    def test_wrong_password_stops_relaunching(self):
        self.plan = ["wrong"]
        code, _, err = self.run_e2e()
        self.assert_failed_at("client launch", code, err)
        self.assertIn("Wrong password", err)
        self.assertEqual(self.launches, 1)

    def test_client_dead_after_login(self):
        with mock.patch.object(e2e, "_alive", lambda pid: False):
            code, _, err = self.run_e2e()
        self.assert_failed_at("client launch", code, err)
        self.assertIn("died within 120 s after login", err)

    def test_unclean_shutdown(self):
        (self.sd / "fail-stop").write_text("")
        code, out, err = self.run_e2e()
        self.assert_failed_at("server shutdown", code, err)
        self.assertIn("E2E: FAIL", out)

    def test_lock_refuses_a_second_run(self):
        (self.root / ".e2e.lock").mkdir()
        (self.root / "evidence").mkdir()
        (self.root / "evidence" / "server.log").write_text("the active run's")
        code, out, err = self.run_e2e()
        self.assertEqual(code, 1)
        self.assertIn("another e2e run is active", err)
        self.assertTrue((self.root / ".e2e.lock").is_dir())
        self.assertEqual((self.root / "evidence" / "server.log").read_text(), "the active run's")
        self.assertFalse((self.sd / "script-calls.log").exists())
        self.server_install.assert_not_called()

    def test_wine_overrides_ride_on_the_launch_and_scope_the_client_lookup(self):
        # Relative, as a user may set them: LaunchServices starts the Launcher
        # elsewhere, so they must reach it resolved against this directory.
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        wine, prefix = self.tmp.resolve() / "my wine", self.tmp.resolve() / "p" / "x"
        opened, scoped = [], []
        real_run = e2e.proc.run

        def run(argv, **kwargs):
            if argv[0] != e2e.client_runtime.OPEN:
                return real_run(argv, **kwargs)
            opened.append([str(a) for a in argv])
            self._launch(None, argv[-2], argv[-1])
            return subprocess.CompletedProcess(argv, 0, "", "")

        def game_pids(checkout):
            scoped.append((checkout.wine_home, checkout.prefix))
            return self._game_pids(checkout)

        self.kill.side_effect = lambda checkout: scoped.append((checkout.wine_home,
                                                                checkout.prefix))
        with mock.patch.object(e2e, "_launch", REAL_LAUNCH), \
                mock.patch.object(e2e.proc, "run", run), \
                mock.patch.object(e2e.client_runtime, "game_pids", game_pids):
            code, out, err = run_cli(["dev", "e2e", ACCOUNT, PASSWORD], self.root,
                                     env={"DAOC_WINE_HOME": "my wine",
                                          "DAOC_WINEPREFIX": "p/x"})
        self.assertEqual(code, 0, err)
        self.assertEqual(len(opened), 1)
        argv = opened[0]
        envs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
        self.assertIn(f"DAOC_WINE_HOME={wine}", envs)
        self.assertIn(f"DAOC_WINEPREFIX={prefix}", envs)
        self.assertTrue(scoped)
        self.assertEqual(set(scoped), {(wine, prefix)})


class MovePortsTest(unittest.TestCase):
    def test_first_match_of_each_kind_per_line(self):
        text = "<Port>10300</Port><Port>10300</Port>\n<UdpPort>10400</UdpPort>\n<Port>10301</Port>\n"
        self.assertEqual(e2e.move_ports(text),
                         "<Port>20300</Port><Port>10300</Port>\n<UdpPort>20400</UdpPort>\n"
                         "<Port>10301</Port>\n")


class DetachedStartTest(unittest.TestCase):
    def test_exited_server_is_reaped_so_kill_0_sees_it_gone(self):
        # daoc-server.sh stop polls `kill -0`; a zombie child of daoc would look
        # alive until its 120 s timeout.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = tmp / "server.sh"
            script.write_text('#!/bin/sh\necho "$$" > pid\necho started\nsleep 0.2\n')
            script.chmod(0o755)
            log = tmp / "console.out"
            e2e._start_detached([script], tmp, log)
            deadline = real_time.monotonic() + 5
            while not (tmp / "pid").exists() and real_time.monotonic() < deadline:
                real_time.sleep(0.02)
            pid = int((tmp / "pid").read_text())
            while real_time.monotonic() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                real_time.sleep(0.05)
            else:
                self.fail(f"pid {pid} still visible to kill -0 after it exited")
            self.assertEqual(log.read_text(), "started\n")


if __name__ == "__main__":
    unittest.main()
