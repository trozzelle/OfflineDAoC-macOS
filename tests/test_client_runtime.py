"""client start/stop/kill/login: watchdog decisions, process scoping, Keychain argv."""
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import ROOT  # noqa: F401  (puts the Checkout on sys.path)

from daoc_cli import client_runtime, keychain, watchdog
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError


def run_watch(samples, before=0, size=0, cs=0):
    watch = watchdog.start(before, size, cs)
    for sample in samples:
        verdict, watch = watchdog.step(watch, watchdog.Sample(*sample))
        if verdict != watchdog.WAIT:
            return verdict, watch
    return watchdog.WAIT, watch


class WatchdogTest(unittest.TestCase):
    def test_new_world_entry_is_success(self):
        verdict, watch = run_watch([(5, 10, 0), (5, 20, 0), (6, 30, 0)], before=5)
        self.assertEqual((verdict, watch.waited), (watchdog.IN_WORLD, 30))

    def test_static_log_and_idle_cpu_is_hung_at_60s(self):
        verdict, watch = run_watch([(0, 100, 10 * i) for i in range(1, 20)], size=100)
        self.assertEqual((verdict, watch.waited, watch.stall), (watchdog.HUNG, 60, 60))

    def test_static_log_with_busy_cpu_is_not_hung(self):
        verdict, watch = run_watch([(0, 100, 60 * i) for i in range(1, 30)], size=100)
        self.assertEqual((verdict, watch.waited), (watchdog.TIMEOUT, 240))

    def test_growing_log_resets_stall(self):
        samples = [(0, 100, 0)] * 5 + [(0, 200, 0)] + [(0, 200, 0)] * 6
        verdict, watch = run_watch(samples, size=100)
        self.assertEqual((verdict, watch.waited), (watchdog.HUNG, 120))

    def test_cap_is_240s(self):
        verdict, watch = run_watch([(0, i, 0) for i in range(1, 40)])
        self.assertEqual((verdict, watch.waited), (watchdog.TIMEOUT, 240))

    def test_cpu_parsing_skips_launcher_and_start_exe(self):
        ps = ("   0:01.50 game.dll 127.0.0.1 10300\n"
              "1:00:00.00 /bin/bash /x/DAoCLauncher.app/Contents/MacOS/launch wine game.dll\n"
              "   0:09.00 C:\\windows\\command\\start.exe game.dll\n"
              "   1:02.00 game.dll\n")
        self.assertEqual(watchdog.game_cputime_cs(ps), 150 + 6200)

    def test_linkdead(self):
        self.assertTrue(watchdog.linkdead_pending("Linkdead player Foo\n"))
        self.assertFalse(watchdog.linkdead_pending("Linkdead player Foo\nFoo just disconnected\n"))
        self.assertFalse(watchdog.linkdead_pending(""))


def fake_run(table):
    """proc.run stand-in: table maps a tuple argv prefix to stdout."""
    calls = []

    def run(argv, **kwargs):
        argv = [os.fspath(a) for a in argv]
        calls.append(argv)
        out = ""
        for prefix, text in table.items():
            if tuple(argv[:len(prefix)]) == prefix:
                out = text(argv) if callable(text) else text
        return mock.Mock(returncode=0, stdout=out, stderr="")
    return run, calls


class ProcessScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "dist" / "wine" / "bin").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"DAOC_WINE_HOME": "", "DAOC_WINEPREFIX": ""}):
            self.checkout = Checkout(self.root)
        self.mine = str(self.root / "dist" / "wine")

    def lsof(self, argv):
        pid = argv[argv.index("-p") + 1]
        home = self.mine if pid == "101" else "/other/checkout/dist/wine"
        # A foreign path that shares our prefix must not match either.
        return f"p{pid}\nn{home}/lib/wine/x86_64-windows/ntdll.dll\nn{self.mine}-old/bin/wine\n"

    def test_game_pids_only_this_checkout(self):
        run, _ = fake_run({
            (client_runtime.PS,): "101 game.dll 127.0.0.1\n202 game.dll 127.0.0.1\n"
                                  "303 /bin/bash /x/MacOS/launch wine game.dll\n",
            (client_runtime.LSOF,): self.lsof,
        })
        with mock.patch.object(client_runtime.proc, "run", run):
            self.assertEqual(client_runtime.game_pids(self.checkout), [101])

    def test_kill_never_signals_foreign_wine(self):
        run, calls = fake_run({
            (client_runtime.PGREP,): "101\n202\n",
            (client_runtime.LSOF,): self.lsof,
        })
        with mock.patch.object(client_runtime.proc, "run", run), \
                mock.patch.object(client_runtime.os, "kill") as kill:
            client_runtime.kill(self.checkout)
        kill.assert_called_once_with(101, 9)
        self.assertIn([client_runtime.PKILL, "-f",
                       str(self.root / "dist" / "DAoCLauncher.app" / "Contents" / "MacOS" / "launch")],
                      calls)

    def test_wine_home_mapped_needs_trailing_slash(self):
        self.assertFalse(client_runtime.wine_home_mapped("n/a/wine-old/x\n", "/a/wine"))
        self.assertTrue(client_runtime.wine_home_mapped("n/a/wine/x\n", "/a/wine"))


class CharacterAndLaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        data = root / "server" / "dist" / "daoc-server" / "data"
        data.mkdir(parents=True)
        con = sqlite3.connect(str(data / "opendaoc.sqlite3.db"))
        con.execute("CREATE TABLE DOLCharacters (Name, Realm, AccountName, LastPlayed, AccountSlot)")
        con.executemany("INSERT INTO DOLCharacters VALUES (?,?,?,?,?)", [
            ("Old", 1, "acct", "2026-01-01", 0), ("Recent", 2, "ACCT", "2026-06-01", 1)])
        con.commit()
        con.close()
        self.checkout = Checkout(root)
        patcher = mock.patch.object(keychain, "read", return_value=("acct", "s3cret"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_most_recent_character(self):
        with mock.patch.dict(os.environ, {"DAOC_CHARACTER": ""}):
            self.assertEqual(client_runtime.character(self.checkout), "Recent")

    def test_daoc_character_override(self):
        with mock.patch.dict(os.environ, {"DAOC_CHARACTER": "Old"}):
            self.assertEqual(client_runtime.character(self.checkout), "Old")
        with mock.patch.dict(os.environ, {"DAOC_CHARACTER": "Nobody"}):
            with self.assertRaises(DaocError):
                client_runtime.character(self.checkout)

    def test_port_override_config_and_default(self):
        with mock.patch.dict(os.environ, {"DAOC_PORT": ""}):
            self.assertEqual(client_runtime.default_port(self.checkout), 10300)
            config = self.checkout.server_dir / "config"
            config.mkdir()
            (config / "serverconfig.xml").write_text("<x><Port>10400</Port></x>")
            self.assertEqual(client_runtime.default_port(self.checkout), 10400)
        with mock.patch.dict(os.environ, {"DAOC_PORT": "10555"}):
            self.assertEqual(client_runtime.default_port(self.checkout), 10555)

    def test_launch_argv_forwards_only_set_env(self):
        argv = client_runtime.launch_argv(
            self.checkout, "acct", "pw", "Recent", 2, 10300,
            {"ROSETTA_X87_PATH": "", "MTL_HUD_ENABLED": "1", "OTHER": "x"})
        self.assertEqual(argv[:3], [client_runtime.OPEN, "-n", str(self.checkout.launcher_app)])
        self.assertIn("WINEDEBUG=trace+frametime", argv)
        self.assertIn("ROSETTA_X87_PATH=", argv)
        self.assertIn("MTL_HUD_ENABLED=1", argv)
        self.assertNotIn("OTHER=x", argv)
        self.assertEqual(argv[argv.index("--args"):],
                         ["--args", "wine", "game.dll", "127.0.0.1", "10300", "42",
                          "acct", "pw", "Recent", "2"])


class LoginTest(unittest.TestCase):
    def test_password_never_on_argv(self):
        run, calls = fake_run({(keychain.SECURITY, "find-generic-password"): "s3cret\n"})
        stdin = mock.Mock(isatty=mock.Mock(return_value=True))
        with mock.patch.object(keychain.proc, "run", run), \
                mock.patch.object(keychain.sys, "stdin", stdin), \
                mock.patch("builtins.input", return_value="acct"), \
                mock.patch.object(keychain.sys, "stderr", io.StringIO()):
            keychain.save_interactive()
        adds = [c for c in calls if c[1] == "add-generic-password"]
        self.assertEqual(adds[0][-2:], ["-w", "acct"])
        self.assertEqual(adds[1][-3:], ["-a", "login_password", "-w"])
        self.assertTrue(all("s3cret" not in c for c in calls))

    def test_login_needs_terminal(self):
        stdin = mock.Mock(isatty=mock.Mock(return_value=False))
        with mock.patch.object(keychain.sys, "stdin", stdin):
            with self.assertRaises(DaocError):
                keychain.save_interactive()


class FakeSecurity:
    """proc.run stand-in for /usr/bin/security with a login keychain that may be
    locked (exit 36, as in an SSH session) and items that may be missing (exit 44)."""

    def __init__(self, locked, items, unlock_ok=True):
        self.locked, self.items, self.unlock_ok = locked, dict(items), unlock_ok
        self.calls = []

    def __call__(self, argv, **kwargs):
        argv = [os.fspath(a) for a in argv]
        self.calls.append(argv)
        verb = argv[1]
        if verb == "unlock-keychain":
            self.locked = not self.unlock_ok
            return mock.Mock(returncode=0 if self.unlock_ok else 51, stdout=None, stderr=None)
        if self.locked:
            return mock.Mock(returncode=36, stdout="",
                             stderr="security: User interaction is not allowed.\n")
        account = argv[argv.index("-a") + 1]
        if verb == "find-generic-password":
            if account not in self.items:
                return mock.Mock(returncode=44, stdout="", stderr="item could not be found\n")
            return mock.Mock(returncode=0, stdout=self.items[account] + "\n", stderr="")
        self.items[account] = argv[argv.index("-w") + 1] if argv[-1] != "-w" else "typed"
        return mock.Mock(returncode=0, stdout="", stderr="")


class KeychainLockTest(unittest.TestCase):
    SAVED = {"login_account": "acct", "login_password": "s3cret"}

    def read(self, security, tty):
        stdin = mock.Mock(isatty=mock.Mock(return_value=tty))
        err = io.StringIO()
        with mock.patch.object(keychain.proc, "run", security), \
                mock.patch.object(keychain.sys, "stdin", stdin), \
                mock.patch.object(keychain.sys, "stderr", err):
            return keychain.read(), err.getvalue()

    def test_locked_keychain_on_a_tty_is_unlocked_then_read(self):
        security = FakeSecurity(locked=True, items=self.SAVED)
        creds, err = self.read(security, tty=True)
        self.assertEqual(creds, ("acct", "s3cret"))
        unlocks = [c for c in security.calls if c[1] == "unlock-keychain"]
        self.assertEqual(unlocks, [[keychain.SECURITY, "unlock-keychain"]])  # security prompts itself
        self.assertIn("locked", err)

    def test_locked_keychain_off_a_tty_says_locked_not_missing(self):
        security = FakeSecurity(locked=True, items=self.SAVED)
        with self.assertRaises(DaocError) as cm:
            self.read(security, tty=False)
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("locked", cm.exception.msg)
        self.assertIn("security unlock-keychain", cm.exception.msg)
        self.assertNotIsInstance(cm.exception, keychain.NotSaved)
        self.assertFalse(any(c[1] == "unlock-keychain" for c in security.calls))

    def test_missing_item_is_not_saved(self):
        with self.assertRaises(keychain.NotSaved):
            self.read(FakeSecurity(locked=False, items={}), tty=True)

    def test_failed_unlock_never_falls_through_to_saving_a_new_account(self):
        security = FakeSecurity(locked=True, items=self.SAVED, unlock_ok=False)
        stdin = mock.Mock(isatty=mock.Mock(return_value=True))
        with mock.patch.object(keychain.proc, "run", security), \
                mock.patch.object(keychain.sys, "stdin", stdin), \
                mock.patch.object(client_runtime.sys, "stdin", stdin), \
                mock.patch.object(keychain.sys, "stderr", io.StringIO()), \
                mock.patch("builtins.input", side_effect=AssertionError("asked for an account")):
            with self.assertRaises(DaocError) as cm:
                client_runtime._credentials()
        self.assertIn("unlock", cm.exception.msg)
        self.assertFalse(any(c[1] == "add-generic-password" for c in security.calls))

    def test_login_unlocks_before_saving(self):
        security = FakeSecurity(locked=True, items={})
        stdin = mock.Mock(isatty=mock.Mock(return_value=True))
        with mock.patch.object(keychain.proc, "run", security), \
                mock.patch.object(keychain.sys, "stdin", stdin), \
                mock.patch.object(keychain.sys, "stderr", io.StringIO()), \
                mock.patch("builtins.input", return_value="acct"):
            keychain.save_interactive()
        verbs = [c[1] for c in security.calls]
        self.assertLess(verbs.index("unlock-keychain"), verbs.index("add-generic-password"))
        self.assertEqual(security.items["login_account"], "acct")


if __name__ == "__main__":
    unittest.main()
