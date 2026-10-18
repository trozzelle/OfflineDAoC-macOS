"""daoc server update: patch pre-check, stop-and-ask, Local pin + rebuild, Progress upgrade ask.

git, the build (server.install), daoc-server.sh status and the GitHub lookup are stubbed.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import games, pins, proc, selection, server, updates
from daoc_cli.selection import Selection
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

NEW_SHA = "abcdef012345" + "9" * 28


class Stdin(io.StringIO):
    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


class ServerUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_checkout(self.tmp.name)
        self.co = Checkout(self.root)
        patches = self.root / "server" / "patches" / "0.35"
        patches.mkdir(parents=True)
        for name in ("020-b.patch", "010-a.patch", "README.md"):
            (patches / name).write_text("patch\n")
        self.co.server_dir.mkdir(parents=True)
        for name in ("daoc-server.sh", "daoc-progress"):
            (self.co.server_dir / name).write_text("#!/bin/sh\n")
            (self.co.server_dir / name).chmod(0o755)
        self.world = self.co.server_dir / "defaults" / "world.sqlite"
        self.world.parent.mkdir()
        self.world.write_bytes(b"old world")
        self.manifest = (self.root / "manifest.json").read_bytes()
        self.latest = {"upstream": self.co.manifest["versions"]["0.35"]["server"]["upstream"], "ref": NEW_SHA}
        self.failing = None
        self.states = [(False, "stopped")]
        self.new_world = b"new world"
        self.build_fails = False
        self.calls = []
        self.installs = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fake_run(self, argv, cwd=None, env=None, verbose=False, check=True):
        args = [str(a) for a in argv]
        self.calls.append(args)
        rc = 0
        if args[0] == "git" and "--check" in args and args[-1].endswith(str(self.failing)):
            rc = 1
        return subprocess.CompletedProcess(args, rc, "", "")

    def fake_status(self, checkout):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def fake_install(self, checkout, version, verbose=False, pin=None):
        self.installs.append(pin if pin is not None else pins.effective(checkout, "server", "0.35"))
        self.world.write_bytes(self.new_world)
        if self.build_fails:
            raise DaocError("build-release.sh failed")

    def update(self, stdin: str = "", tty: bool = False):
        with mock.patch.object(updates, "resolve_latest", lambda co, group, version=None: dict(self.latest)), \
                mock.patch.object(proc, "run", self.fake_run), \
                mock.patch.object(server, "status", self.fake_status), \
                mock.patch.object(server, "install", self.fake_install), \
                mock.patch.object(sys, "stdin", Stdin(stdin, tty)):
            return run_cli(["server", "update"], self.root)

    def git_calls(self):
        return [c[3:] if c[1] == "-C" else c[1:] for c in self.calls if c[0] == "git"]

    def progress_calls(self):
        return [c for c in self.calls if c[0].endswith("daoc-progress")]

    def local(self):
        return pins.local(Checkout(self.root), "server", "0.35")

    def test_already_at_latest(self) -> None:
        self.latest["ref"] = self.co.manifest["versions"]["0.35"]["server"]["ref"]
        pins.record_installed(self.co, "server", self.latest)
        code, _, err = self.update()
        self.assertEqual(code, 0)
        self.assertIn(f"server already at {self.latest['ref'][:12]}", err)
        self.assertEqual((self.calls, self.installs), ([], []))

    def test_already_at_latest_behind_a_lapsed_local_pin_repins_without_a_rebuild(self) -> None:
        pins.set_local(self.co, "server", self.latest, "0.35")
        pins.record_installed(self.co, "server", self.latest)
        manifest = json.loads(self.manifest)
        manifest["versions"]["0.35"]["server"]["ref"] = "b" * 40
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        code, _, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn(f"server already at {NEW_SHA[:12]}", err)
        self.assertEqual((self.calls, self.installs), ([], []))
        self.assertEqual(pins.effective(Checkout(self.root), "server", "0.35"), self.latest)

    def test_install_behind_a_newer_shipped_pin_is_rebuilt(self) -> None:
        # A pull brought a Shipped pin naming upstream's latest; the install is older.
        manifest = json.loads(self.manifest)
        manifest["versions"]["0.35"]["server"]["ref"] = NEW_SHA
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        pins.record_installed(self.co, "server", {"upstream": self.latest["upstream"],
                                                  "ref": "1" * 40})
        self.new_world = b"old world"
        code, _, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertNotIn("already at", err)
        self.assertEqual(self.installs, [self.latest])
        self.assertIsNone(self.local())

    def test_failing_patch_leaves_the_pin_unchanged(self) -> None:
        self.failing = "020-b.patch"
        code, _, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("020-b.patch no longer applies", err)
        self.assertIsNone(self.local())
        self.assertEqual(self.installs, [])
        patches = self.co.root / "server" / "patches" / "0.35"
        calls = self.git_calls()
        self.assertEqual(calls[0][:4], ["clone", "--quiet", "--filter=blob:none", self.latest["upstream"]])
        self.assertEqual(calls[1:], [
            ["checkout", "--quiet", "--detach", NEW_SHA],
            ["apply", "--check", str(patches / "010-a.patch")],
            ["apply", str(patches / "010-a.patch")],
            ["apply", "--check", str(patches / "020-b.patch")],
        ])

    def test_running_off_a_tty_is_refused_without_a_rebuild(self) -> None:
        self.states = [(True, "running (pid 42)")]
        code, _, err = self.update()
        self.assertEqual(code, 2)
        self.assertIn("the server is running", err)
        self.assertIsNone(self.local())
        self.assertEqual(self.installs, [])

    def test_running_on_a_tty_answer_no_is_refused(self) -> None:
        self.states = [(True, "running (pid 42)")]
        code, _, err = self.update("n\n", tty=True)
        self.assertEqual(code, 2)
        self.assertIn("refused", err)
        self.assertNotIn("stop", [c[-1] for c in self.calls])
        self.assertEqual(self.installs, [])

    def test_running_on_a_tty_answer_yes_stops_then_rebuilds(self) -> None:
        self.states = [(True, "running (pid 42)"), (False, "stopped")]
        self.new_world = b"old world"
        code, _, _ = self.update("y\n", tty=True)
        self.assertEqual(code, 0)
        self.assertIn([str(self.co.server_dir / "daoc-server.sh"), "stop"], self.calls)
        self.assertEqual(len(self.installs), 1)

    def test_failed_build_leaves_the_pin_unchanged_and_a_rerun_rebuilds(self) -> None:
        self.build_fails = True
        code, _, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("build-release.sh failed", err)
        self.assertEqual(self.installs, [self.latest])
        self.assertIsNone(self.local())

        self.build_fails = False
        self.world.write_bytes(b"old world")
        code, _, err = self.update()
        self.assertEqual(code, 0)
        self.assertNotIn("already at", err)
        self.assertEqual(self.installs, [self.latest, self.latest])
        self.assertEqual(self.local(), self.latest)
        self.assertIn("daoc progress upgrade", err)

    def test_world_change_off_a_tty_prints_the_hint_and_runs_no_upgrade(self) -> None:
        code, _, err = self.update()
        self.assertEqual(code, 0)
        self.assertIn("daoc progress upgrade", err)
        self.assertEqual(self.progress_calls(), [])
        self.assertEqual(self.installs, [self.latest])
        self.assertEqual(self.local(), self.latest)
        self.assertEqual((self.root / "manifest.json").read_bytes(), self.manifest)

    def test_world_change_on_a_tty_answer_no_runs_no_upgrade(self) -> None:
        code, out, err = self.update("n\n", tty=True)
        self.assertEqual(code, 0)
        self.assertIn("keep and relic ownership", err)
        self.assertIn("Run the Progress upgrade now? [y/N]", err)
        self.assertEqual(out, "")
        self.assertEqual(self.progress_calls(), [])

    def test_world_change_on_a_tty_answer_yes_runs_the_upgrade(self) -> None:
        code, _, err = self.update("yes\n", tty=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.progress_calls(), [[str(self.co.server_dir / "daoc-progress"), "upgrade",
                                                  "--edition=sluaghbinder"]])
        self.assertIn("Progress upgrade: done", err)

    def test_update_records_the_selected_edition(self) -> None:
        selection.save(self.co, Selection(games.parse("0.35"), "original"))
        code, _, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertEqual((self.co.server_dir / "config" / "edition").read_text(), "classic\n")

    def test_unchanged_world_asks_nothing(self) -> None:
        self.new_world = b"old world"
        code, out, err = self.update("y\n", tty=True)
        self.assertEqual(code, 0)
        self.assertNotIn("progress upgrade", (out + err).lower())
        self.assertEqual(self.progress_calls(), [])


if __name__ == "__main__":
    unittest.main()
