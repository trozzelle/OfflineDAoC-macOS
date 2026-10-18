"""daoc client start/stop/kill for the New client (Godot), and what stays Original-client only."""
import io
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import client_runtime, games, keychain, selection, watchdog
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.selection import Selection


class NewClientRuntimeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(tmp.name)
        self.co = Checkout(self.root)
        selection.save(self.co, Selection(games.parse("0.36b"), "new"))
        (self.co.godot_app / "Contents" / "MacOS").mkdir(parents=True)
        (self.co.godot_app / "Contents" / "MacOS" / "Godot").write_text("")
        self.co.new_client_project.mkdir(parents=True)
        (self.co.new_client_project / "project.godot").write_text("")
        logs = self.co.server_dir / "logs"
        logs.mkdir(parents=True)
        self.slog = logs / "server.log"
        self.slog.write_text("")
        self.launches = []
        self.server_says = ["LoginRequestHandler: User acct logging on! (ver 1.127)\n"]
        self.ps = ""
        patches = [
            mock.patch.object(keychain, "read", return_value=("acct", "pw")),
            mock.patch.object(client_runtime.time, "sleep"),
            mock.patch.object(client_runtime.proc, "run", self.fake_run),
            mock.patch.object(client_runtime, "game_pids", return_value=[]),
            mock.patch.dict(os.environ, {"DAOC_PORT": ""}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, argv, **kwargs):
        argv = [os.fspath(a) for a in argv]
        if argv[0] == client_runtime.OPEN:
            self.launches.append(argv)
            with self.slog.open("a") as f:
                f.writelines(self.server_says)
        out = self.ps if argv[0] == client_runtime.PS else ""
        return mock.Mock(returncode=0, stdout=out, stderr="")

    def start(self):
        err = io.StringIO()
        with mock.patch.object(client_runtime.sys, "stderr", err):
            client_runtime.start(self.co, client="new")
        return err.getvalue()

    def test_new_argv_exact(self):
        argv = client_runtime.new_launch_argv(self.co, "acct", "pw", classic=False)
        self.assertEqual(argv, [
            client_runtime.OPEN, "-n", str(self.co.godot_app),
            "--env", f"DOTNET_ROOT={Path.home() / '.dotnet'}",
            "--stdout", str(client_runtime.NEW_LOG), "--stderr", str(client_runtime.NEW_LOG),
            "--args", "--path", str(self.co.new_client_project), "--",
            "--server=127.0.0.1", "--account=acct", "--password=pw",
        ])
        classic = client_runtime.new_launch_argv(self.co, "acct", "pw", classic=True)
        self.assertEqual(classic, argv + ["--custom-class=off"])

    def test_classic_game_starts_without_the_custom_class(self):
        selection.save(self.co, Selection(games.parse("0.36"), "new"))
        self.start()
        self.assertEqual(self.launches[0][-1], "--custom-class=off")

    def test_new_success_on_login_line(self):
        err = self.start()
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(self.launches[0][-1], "--password=pw")
        self.assertIn("logged in after", err)

    def test_new_refuses_other_port(self):
        with mock.patch.dict(os.environ, {"DAOC_PORT": "20300"}), self.assertRaises(DaocError) as cm:
            self.start()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("10300", cm.exception.msg)
        self.assertEqual(self.launches, [])

    def test_new_refuses_a_game_without_a_new_client(self):
        # The 0.36c client stays installed after a switch to 0.35b, but cannot play it.
        selection.save(self.co, Selection(games.parse("0.35b"), "original"))
        with self.assertRaises(DaocError) as cm:
            self.start()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("0.35b", cm.exception.msg)
        self.assertEqual(self.launches, [])

    def test_new_refuses_character_flag(self):
        with self.assertRaises(DaocError) as cm:
            client_runtime._start(mock.Mock(client="new", character="Spikeone", dry_run=False, retries=1),
                                  self.co)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.launches, [])

    def test_new_refuses_when_not_installed(self):
        (self.co.new_client_project / "project.godot").unlink()
        with self.assertRaises(DaocError) as cm:
            self.start()
        self.assertIn("daoc client install --client new", cm.exception.msg)

    def test_refuses_when_other_client_running(self):
        client_runtime.game_pids.return_value = [5]
        with self.assertRaises(DaocError) as cm:
            self.start()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("original client is running", cm.exception.msg)
        self.assertEqual(self.launches, [])

    def test_new_wrong_password(self):
        self.server_says.append("LoginRequestHandler: Wrong password!\n")
        with self.assertRaises(DaocError) as cm:
            self.start()
        self.assertIn("password", cm.exception.msg)

    def test_new_timeout_kills(self):
        self.server_says = []
        with mock.patch.object(client_runtime, "kill_new") as kill_new, self.assertRaises(DaocError) as cm:
            self.start()
        kill_new.assert_called_once_with(self.co)
        self.assertIn(f"{watchdog.CAP}s", cm.exception.msg)

    def test_kill_targets_only_this_checkouts_godot(self):
        mine = f"{self.co.godot_app}/Contents/MacOS/Godot --path {self.co.new_client_project}"
        self.ps = (f"101 {mine}\n"
                   "202 /other/checkout/dist/godot/Godot_mono.app/Contents/MacOS/Godot --path x\n"
                   f"303 /bin/sh -c echo {self.co.godot_app}/Contents/MacOS/Godot\n")
        self.assertEqual(client_runtime.new_pids(self.co), [101])
        signals = []

        def kill(pid, sig):
            signals.append((pid, sig))
            self.ps = ""  # gone after SIGTERM

        with mock.patch.object(client_runtime.os, "kill", kill):
            client_runtime.kill_new(self.co)
        self.assertEqual(signals, [(101, signal.SIGTERM)])

    def test_running_client(self):
        self.assertIsNone(client_runtime.running_client(self.co))
        self.ps = f"101 {self.co.godot_app}/Contents/MacOS/Godot --path x\n"
        self.assertEqual(client_runtime.running_client(self.co), "new")
        client_runtime.game_pids.return_value = [5]
        self.assertEqual(client_runtime.running_client(self.co), "original")

    def test_bench_and_graphics_refuse_new_default(self):
        for argv in (["client", "bench"], ["graphics", "status"]):
            with self.subTest(argv=argv):
                code, _, err = run_cli(argv, self.root)
                self.assertEqual(code, 2)
                self.assertIn("original client", err)


class NewProcessTest(unittest.TestCase):
    def test_is_new_client_process(self):
        app = "/c/dist/godot/Godot_mono.app"
        self.assertTrue(watchdog.is_new_client_process(f"{app}/Contents/MacOS/Godot --path x", app))
        self.assertFalse(watchdog.is_new_client_process(f"/bin/sh {app}/Contents/MacOS/Godot", app))
        self.assertFalse(watchdog.is_new_client_process(f"{app}-old/Contents/MacOS/Godot", app))


if __name__ == "__main__":
    unittest.main()
