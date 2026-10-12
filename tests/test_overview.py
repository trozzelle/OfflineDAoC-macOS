"""`daoc` with no arguments: installs, server state, pins, behind, commands."""
import hashlib
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import pins
from daoc_cli.checkout import Checkout

NEW_REF = "0123456789abcdef0123456789abcdef01234567"


def line(out, prefix):
    found = [l for l in out.splitlines() if l.startswith(prefix)]
    if len(found) != 1:
        raise AssertionError(f"expected one line starting {prefix!r} in:\n{out}")
    return found[0]


def pin_row(out, group):
    return line(out, group + " ").split()


class OverviewTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = make_checkout(self.tmp)
        self.co = Checkout(self.root)

    def overview(self, env=None):
        code, out, err = run_cli([], self.root, env)
        self.assertEqual(code, 0, err)
        return out, err

    def server_install(self, status_body):
        """A Server install whose daoc-server.sh logs its argv and runs status_body."""
        self.co.server_dir.mkdir(parents=True)
        (self.co.server_dir / "VERSION").write_text("abc1234\n")
        script = self.co.server_dir / "daoc-server.sh"
        script.write_text(f'#!/bin/sh\necho "$@" >> "$(dirname "$0")/calls"\n{status_body}\n')
        script.chmod(0o755)
        return self.co.server_dir / "calls"

    def test_empty_checkout_says_not_installed(self):
        out, err = self.overview()
        self.assertEqual(err, "")
        self.assertRegex(line(out, "Server install:"), r"not installed$")
        self.assertRegex(line(out, "Server running:"), r"no$")
        self.assertRegex(line(out, "Client install:"), r"not installed$")
        self.assertNotIn("behind", out)
        for group in pins.GROUPS:
            row = pin_row(out, group)
            self.assertEqual(row[1], pins.short(group, pins.shipped(self.co, group)))
            self.assertEqual(row[2], "-")
            self.assertEqual(row[3:], ["not", "installed"])
        self.assertNotIn("rebuild due", out)

    def test_command_list_has_groups_but_not_dev(self):
        out, _ = self.overview()
        commands = out.split("Commands:\n", 1)[1]
        for group in ("server", "client", "admin", "progress", "graphics"):
            self.assertRegex(commands, rf"(?m)^  daoc {group}\s")
        self.assertNotRegex(commands, r"\bdaoc dev\b")
        self.assertNotIn("SUPPRESS", out)

    def test_local_pin_is_shown(self):
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        out, _ = self.overview()
        self.assertEqual(pin_row(out, "graphics")[2], NEW_REF[:12])
        self.assertEqual(pin_row(out, "server")[2], "-")

    def test_running_follows_status(self):
        calls = self.server_install('echo "running (pid 42)"')
        out, _ = self.overview()
        self.assertRegex(line(out, "Server install:"), r"present \(port build abc1234\)$")
        self.assertRegex(line(out, "Server running:"), r"yes \(pid 42\)$")
        self.assertEqual(calls.read_text(), "status\n")
        self.assertEqual(pin_row(out, "server")[3], "unknown")

    def test_stopped_server_is_not_running(self):
        self.server_install("echo stopped")
        out, _ = self.overview()
        self.assertRegex(line(out, "Server running:"), r"no$")

    def test_failing_status_is_unknown(self):
        self.server_install("exit 3")
        out, _ = self.overview()
        self.assertRegex(line(out, "Server running:"), r"unknown \(daoc-server.sh status exit 3\)$")

    def test_server_built_from_its_recorded_pin(self):
        self.server_install("echo stopped")
        shipped = pins.shipped(self.co, "server")
        pins.record_installed(self.co, "server", shipped)
        out, _ = self.overview()
        self.assertEqual(pin_row(out, "server")[3:], [shipped["ref"][:12]])

        pins.record_installed(self.co, "server", dict(shipped, ref=NEW_REF))
        out, _ = self.overview()
        self.assertEqual(pin_row(out, "server")[3:], [NEW_REF[:12], "rebuild", "due"])

    def test_client_without_a_record_is_only_ever_the_legacy_release(self):
        self.co.client_root.mkdir(parents=True)
        self.co.app_dir.mkdir(parents=True)
        dll = self.co.app_dir / "game.dll.orig"
        dll.write_bytes(b"pristine")
        sha = hashlib.sha256(b"pristine").hexdigest()
        out, _ = self.overview()
        self.assertRegex(line(out, "Client install:"), r"present$")
        self.assertEqual(pin_row(out, "client")[3:], ["game.dll", sha[:12], "rebuild", "due"])
        self.assertIsNone(pins.installed(self.co, "client"))

        # Every Proven release shares the legacy game.dll: a newer pin with that
        # hash must not pass for the 0.35b files on disk.
        legacy = dict(pins.LEGACY_CLIENT, game_dll_sha256=sha)
        pins.set_local(self.co, "client", dict(pins.shipped(self.co, "client"),
                                                version="0.36", game_dll_sha256=sha))
        with mock.patch.object(pins, "LEGACY_CLIENT", legacy):
            out, _ = self.overview()
        self.assertEqual(pin_row(out, "client")[2:], ["0.36", "0.35b", "rebuild", "due"])
        self.assertEqual(pins.installed(self.co, "client"), legacy)

    def test_git_records_behind_and_graphics_head(self):
        (self.root / ".git").mkdir()
        (self.co.graphics_src / ".git").mkdir(parents=True)
        stubs = path_stubs(self.tmp, {"git": "\n".join((
            '[ "$1" = -C ] && shift 2',
            'case "$*" in',
            '  "rev-list --count HEAD..@{u}") echo 3 ;;',
            '  "rev-parse --abbrev-ref @{u}") echo origin/main ;;',
            f'  "rev-parse HEAD") echo {NEW_REF} ;;',
            '  *) exit 1 ;;',
            'esac',
        ))})
        env = {"PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"}
        out, _ = self.overview(env)
        self.assertRegex(line(out, "Checkout:"), r"3 commits behind origin/main")
        self.assertEqual(pin_row(out, "graphics")[3:], [NEW_REF[:12], "rebuild", "due"])

        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        out, _ = self.overview(env)
        self.assertEqual(pin_row(out, "graphics")[2:], [NEW_REF[:12], NEW_REF[:12]])
        self.assertTrue(all(c[0] == "git" for c in stub_calls(stubs)))

    def test_no_upstream_omits_the_behind_line(self):
        (self.root / ".git").mkdir()
        stubs = path_stubs(self.tmp, {"git": "exit 128"})
        out, _ = self.overview({"PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"})
        self.assertNotIn("Checkout:", out)
        self.assertTrue(stub_calls(stubs))

    def test_lapsed_local_pin_prints_notice_and_shows_shipped(self):
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        manifest = self.root / "manifest.json"
        manifest.write_text(re.sub(r'("graphics":\s*\{[^}]*?"ref":\s*")[0-9a-f]+',
                                   r"\g<1>" + "f" * 40, manifest.read_text()))
        code, out, err = run_cli([], self.root)
        self.assertEqual(code, 0)
        self.assertIn(f"daoc: Local graphics pin {NEW_REF[:12]} lapsed; Shipped pin {'f' * 12} applies", err)
        self.assertEqual(pin_row(out, "graphics")[1:3], ["f" * 12, "-"])


if __name__ == "__main__":
    unittest.main()
