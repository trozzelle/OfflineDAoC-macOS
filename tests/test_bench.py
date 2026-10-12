"""client bench: the frame-time verdict and the gm-raise marker lifecycle."""
import io
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import ROOT  # noqa: F401  (puts the Checkout on sys.path)

from daoc_cli import bench, keychain
from daoc_cli.checkout import Checkout


def stamps(frame_ms):
    """Probe timestamps (ns) for a list of frame times (ms)."""
    ts, t = [0], 0
    for ms in frame_ms:
        t += int(ms * 1e6)
        ts.append(t)
    return ts


def judge(frame_ms, vsync="(vsync off, maxFps 0)", moved=1000):
    return bench.verdict(stamps(frame_ms), vsync, "t", 300, "Qunilan", moved)


class VerdictTest(unittest.TestCase):
    def test_steady_60fps_passes(self):
        lines, code = judge([16.0] * 1000)
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], "GATE: PASS (avg >= 60 FPS, p95 <= 16.7 ms)")
        self.assertTrue(lines[0].startswith("[t] renderer (vsync off, maxFps 0); play window 300s, 1000 frames"))

    def test_slow_frames_fail(self):
        lines, code = judge([16.0] * 900 + [40.0] * 100)
        self.assertEqual(code, 1)
        self.assertTrue(lines[-1].startswith("GATE: FAIL"))

    def test_vsync_on_allows_17ms_p95(self):
        frames = [16.0] * 900 + [16.9] * 100
        self.assertEqual(judge(frames)[1], 1)
        lines, code = judge(frames, vsync="(vsync on, maxFps 60)")
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], "GATE: PASS (avg >= 60 FPS, p95 <= 17.0 ms)")

    def test_no_frames_is_invalid(self):
        self.assertEqual(bench.verdict([], "(vsync on, maxFps 60)", "t", 300, "x", 1000),
                         (["INVALID: only 0 frames in the window"], 2))
        self.assertEqual(judge([16.0] * 99)[1], 2)

    def test_not_moving_is_invalid(self):
        lines, code = judge([16.0] * 1000, moved=10)
        self.assertEqual((lines[-1], code),
                         ("INVALID: the character did not move away from the NPC", 2))


class MarkerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.checkout = Checkout(Path(tmp.name))
        (self.checkout.server_dir / "run").mkdir(parents=True)
        self.calls = []
        self.ok = True
        patcher = mock.patch.object(bench, "_admin", side_effect=self.admin)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.err = io.StringIO()
        patcher = mock.patch("sys.stderr", self.err)
        patcher.start()
        self.addCleanup(patcher.stop)

    def admin(self, checkout, *args):
        self.calls.append(args)
        out = '{"role": "player"}' if args[:2] == ("accounts", "show") else ""
        return subprocess.CompletedProcess(args, 0 if self.ok else 1, out, "")

    def test_leftover_is_restored_first_and_cleared(self):
        bench.marker(self.checkout).write_text("alice\n")
        bench.restore_leftover(self.checkout)
        self.assertEqual(self.calls, [("accounts", "set-role", "alice", "player")])
        self.assertFalse(bench.marker(self.checkout).exists())
        self.assertIn("daoc: restored alice to player", self.err.getvalue())

    def test_failed_leftover_restore_is_invalid_and_keeps_marker(self):
        bench.marker(self.checkout).write_text("alice\n")
        self.ok = False
        with self.assertRaises(bench.Invalid):
            bench.restore_leftover(self.checkout)
        self.assertTrue(bench.marker(self.checkout).exists())

    def test_raise_writes_marker_and_restore_clears_it(self):
        bench.raise_gm(self.checkout, "bob")
        self.assertEqual(bench.marker(self.checkout).read_text(), "bob\n")
        self.assertEqual(self.calls[-1], ("accounts", "set-role", "bob", "gm"))
        bench.restore(self.checkout)
        self.assertEqual(self.calls[-1], ("accounts", "set-role", "bob", "player"))
        self.assertFalse(bench.marker(self.checkout).exists())

    def test_failed_restore_keeps_marker_for_next_run(self):
        bench.raise_gm(self.checkout, "bob")
        self.ok = False
        with mock.patch.object(bench.server, "tool", return_value=Path("/x/daoc-admin")):
            bench.restore(self.checkout)
        self.assertTrue(bench.marker(self.checkout).exists())
        self.ok = True
        bench.restore_leftover(self.checkout)
        self.assertEqual(self.calls[-1], ("accounts", "set-role", "bob", "player"))
        self.assertFalse(bench.marker(self.checkout).exists())

    def test_restore_uses_marker_account(self):
        bench.marker(self.checkout).write_text("alice\n")
        bench.restore(self.checkout)
        self.assertEqual(self.calls, [("accounts", "set-role", "alice", "player")])
        self.assertFalse(bench.marker(self.checkout).exists())

    def test_interrupt_before_raise_restores_leftover_only(self):
        bench.marker(self.checkout).write_text("alice\n")
        out = Path(self.checkout.root) / "out"

        def interrupt(_checkout):
            os.kill(os.getpid(), signal.SIGINT)

        with mock.patch.dict(os.environ, {"DAOC_BENCH_ACCOUNT": "bob", "DAOC_BENCH_OUT": str(out)}), \
                mock.patch.object(bench, "_build"), \
                mock.patch.object(bench, "_server_up", return_value=True), \
                mock.patch.object(bench.client_runtime, "character", return_value="Hero"), \
                mock.patch.object(bench.client_runtime, "stop", side_effect=interrupt):
            with self.assertRaises(SystemExit) as cm:
                bench.run(self.checkout, 10, "t")
        self.assertEqual(cm.exception.code, 130)
        self.assertEqual(self.calls, [("accounts", "set-role", "alice", "player")])
        self.assertFalse(bench.marker(self.checkout).exists())
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)


class AccountTest(unittest.TestCase):
    def test_missing_account_is_asked_for_on_a_terminal(self):
        saved = []

        def read():
            if not saved:
                raise keychain.NotSaved()
            return saved[0]

        stdin = mock.Mock(isatty=mock.Mock(return_value=True))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"DAOC_BENCH_OUT": tmp}) as env, \
                mock.patch.object(keychain, "read", side_effect=read), \
                mock.patch.object(keychain, "save_interactive",
                                  side_effect=lambda: saved.append(("acct", "pw"))), \
                mock.patch.object(bench.client_runtime.sys, "stdin", stdin), \
                mock.patch.object(bench, "_bench", return_value=0) as run:
            env.pop("DAOC_BENCH_ACCOUNT", None)
            self.assertEqual(bench.run(Checkout(Path(tmp)), 10, "t"), 0)
        self.assertEqual(run.call_args.args[3], "acct")


if __name__ == "__main__":
    unittest.main()
