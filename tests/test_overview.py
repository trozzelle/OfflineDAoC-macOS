"""`daoc` with no arguments: installs, server state, pins, newer release, commands."""
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import GIT_ENV, git, make_checkout, path_stubs, run_cli, stub_calls

import json
import sqlite3

from daoc_cli import games, mtld3d, pins, selection
from daoc_cli.selection import Selection
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
        self.assertRegex(line(out, "Original client:"), r"not installed$")
        self.assertNotIn("Checkout:", out)
        for group, version in (("server", "0.35"), ("original_client", "0.35"), ("graphics", None)):
            row = pin_row(out, pins.label(group, version))
            self.assertEqual(row[1], pins.short(group, pins.shipped(self.co, group, version)))
            self.assertEqual(row[2], "-")
            self.assertEqual(row[3:], ["not", "installed"])
        self.assertNotIn("rebuild due", out)

    def test_overview_shows_mtld3d_state(self):
        self.assertRegex(line(self.overview()[0], "mtld3d:"), r"^mtld3d:\s+-$")
        wine_home, _ = self.co.flavour_paths("rosetta")
        (wine_home / "bin").mkdir(parents=True)
        (wine_home / "bin" / "wine").write_text("#!/bin/sh\n")
        self.assertRegex(line(self.overview()[0], "mtld3d:"), r"^mtld3d:\s+stock$")
        target = wine_home / mtld3d.TARGETS["rosetta"][0][1]
        target.parent.mkdir(parents=True)
        target.write_bytes(b"fork")
        record = {"version": "v9", "stock": {t: None for _, t in mtld3d.TARGETS["rosetta"]},
                  "fork": {t: hashlib.sha256(b"fork").hexdigest()
                           if t == target.relative_to(wine_home).as_posix() else None
                           for _, t in mtld3d.TARGETS["rosetta"]}}
        (wine_home / mtld3d.RECORD).write_text(json.dumps(record))
        pin = self.co.manifest["mtld3d"]["version"]
        self.assertEqual(line(self.overview()[0], "mtld3d:").split(None, 1)[1],
                         f"fork v9 (pin {pin}: run daoc client install)")
        # At the pinned version: no notice.
        (wine_home / mtld3d.RECORD).write_text(json.dumps(dict(record, version=pin)))
        self.assertRegex(line(self.overview()[0], "mtld3d:"), rf"^mtld3d:\s+fork {re.escape(pin)}$")

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
        self.assertEqual(pin_row(out, "server@0.35")[2], "-")

    def test_running_follows_status(self):
        calls = self.server_install('echo "running (pid 42)"')
        out, _ = self.overview()
        self.assertRegex(line(out, "Server install:"), r"present \(port build abc1234\)$")
        self.assertRegex(line(out, "Server running:"), r"yes \(pid 42\)$")
        self.assertEqual(calls.read_text(), "status\n")
        self.assertEqual(pin_row(out, "server@0.35")[3], "unknown")

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
        shipped = pins.shipped(self.co, "server", "0.35")
        pins.record_installed(self.co, "server", shipped)
        out, _ = self.overview()
        self.assertEqual(pin_row(out, "server@0.35")[3:], [shipped["ref"][:12]])

        pins.record_installed(self.co, "server", dict(shipped, ref=NEW_REF))
        out, _ = self.overview()
        self.assertEqual(pin_row(out, "server@0.35")[3:], [NEW_REF[:12], "rebuild", "due"])

    def test_client_without_a_record_is_only_ever_the_legacy_release(self):
        self.co.client_root.mkdir(parents=True)
        self.co.app_dir.mkdir(parents=True)
        dll = self.co.app_dir / "game.dll.orig"
        dll.write_bytes(b"pristine")
        sha = hashlib.sha256(b"pristine").hexdigest()
        out, _ = self.overview()
        self.assertRegex(line(out, "Original client:"), r"present \(not a known build\)$")
        self.assertEqual(pin_row(out, "original_client@0.35")[3:], ["game.dll", sha[:12], "rebuild", "due"])
        self.assertIsNone(pins.installed(self.co, "original_client"))

        # Every Proven release shares the legacy game.dll: a newer pin with that
        # hash must not pass for the 0.35b files on disk.
        legacy = dict(pins.LEGACY_CLIENT, game_dll_sha256=sha)
        pins.set_local(self.co, "original_client", dict(pins.shipped(self.co, "original_client", "0.35"),
                                                version="0.36", game_dll_sha256=sha), "0.35")
        with mock.patch.object(pins, "LEGACY_CLIENT", legacy):
            out, _ = self.overview()
        self.assertEqual(pin_row(out, "original_client@0.35")[2:], ["0.36", "0.35b", "rebuild", "due"])
        self.assertEqual(pins.installed(self.co, "original_client"), legacy)

    def test_git_records_graphics_head(self):
        (self.root / ".git").mkdir()
        (self.co.graphics_src / ".git").mkdir(parents=True)
        stubs = path_stubs(self.tmp, {"git": "\n".join((
            '[ "$1" = -C ] && shift 2',
            'case "$*" in',
            f'  "rev-parse HEAD") echo {NEW_REF} ;;',
            '  *) exit 1 ;;',
            'esac',
        ))})
        env = {"PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"}
        out, _ = self.overview(env)
        self.assertEqual(pin_row(out, "graphics")[3:], [NEW_REF[:12], "rebuild", "due"])

        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        out, _ = self.overview(env)
        self.assertEqual(pin_row(out, "graphics")[2:], [NEW_REF[:12], NEW_REF[:12]])
        self.assertTrue(all(c[0] == "git" for c in stub_calls(stubs)))

    def test_failing_git_omits_the_checkout_line(self):
        (self.root / ".git").mkdir()
        stubs = path_stubs(self.tmp, {"git": "exit 128"})
        out, _ = self.overview({"PATH": f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"})
        self.assertNotIn("Checkout:", out)
        self.assertTrue(stub_calls(stubs))

    def test_checkout_line_names_the_newest_release_head_lacks(self):
        def commit_tagged(tag=None):
            git("commit", "-q", "--allow-empty", "-m", tag or "next", cwd=self.root)
            if tag:
                git("tag", tag, cwd=self.root)

        git("init", "-q", "-b", "main", cwd=self.root)
        commit_tagged("v0.9.0")
        commit_tagged("v0.10.0")  # newer by version, older by name
        commit_tagged()  # main past the last release

        git("checkout", "-q", "v0.9.0", cwd=self.root)
        out, _ = self.overview(GIT_ENV)
        self.assertEqual(line(out, "Checkout:").split(None, 1)[1],
                         "v0.10.0 available (as of the last fetch): git checkout v0.10.0")
        for ref in ("v0.10.0", "main"):
            git("checkout", "-q", ref, cwd=self.root)
            out, _ = self.overview(GIT_ENV)
            self.assertNotIn("Checkout:", out, ref)

    def test_lapsed_local_pin_prints_notice_and_shows_shipped(self):
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        manifest = self.root / "manifest.json"
        manifest.write_text(re.sub(r'("graphics":\s*\{[^}]*?"ref":\s*")[0-9a-f]+',
                                   r"\g<1>" + "f" * 40, manifest.read_text()))
        code, out, err = run_cli([], self.root)
        self.assertEqual(code, 0)
        self.assertIn(f"daoc: Local graphics pin {NEW_REF[:12]} lapsed; Shipped pin {'f' * 12} applies", err)
        self.assertEqual(pin_row(out, "graphics")[1:3], ["f" * 12, "-"])

    def save(self, value):
        data = self.co.server_dir / "data"
        data.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(data / "opendaoc.sqlite3.db"))
        con.execute('CREATE TABLE ServerProperty ("Key" TEXT, Value TEXT)')
        con.execute("INSERT INTO ServerProperty VALUES ('enable_sluaghbinder', ?)", (value,))
        con.commit()
        con.close()

    def test_game_line(self):
        out, _ = self.overview()
        self.assertEqual(line(out, "Game:").split(None, 1)[1], "0.35b (Sluaghbinder) · default client: original")
        self.assertRegex(line(out, "Save:"), r"none yet$")

    def test_switch_incomplete_hint(self):
        selection.save(self.co, Selection(games.parse("0.35b"), "original", games.parse("0.36")))
        out, _ = self.overview()
        self.assertIn("switch to 0.36 incomplete: run daoc game switch 0.36", out)

    def test_existing_checkout_legacy(self):
        # Review Focus 1: a checkout from before game versions, after git pull.
        (self.root / ".daoc").mkdir()
        (self.root / ".daoc" / "pins.json").write_text(json.dumps([
            {"group": "client", "pin": {"version": "0.35b"}, "replaces": {"version": "0.35b"},
             "at": "2026-10-11T12:00:00Z"}]))
        self.co.app_dir.mkdir(parents=True)
        (self.co.app_dir / "game.dll.orig").write_bytes(b"0.35b pristine")
        sha = hashlib.sha256(b"0.35b pristine").hexdigest()
        self.save("False")
        with mock.patch.object(pins, "LEGACY_CLIENT", dict(pins.LEGACY_CLIENT, game_dll_sha256=sha)):
            code, out, err = run_cli([], self.root)
        self.assertEqual(code, 0, err)
        self.assertIn("Local client pin from before game versions dropped", err)
        self.assertEqual(line(out, "Game:").split(None, 1)[1], "0.35b (Sluaghbinder) · default client: original")
        self.assertRegex(line(out, "Original client:"), r"0\.35b, Sluaghbinder$")
        self.assertRegex(line(out, "Save:"), r"Classic classes$")
        self.assertIn("selected 0.35b: run daoc game switch 0.35b", out)

    def test_original_built_for_another_game(self):
        self.co.app_dir.mkdir(parents=True)
        pins.record_installed(self.co, "original_client", {"version": "0.35b", "edition": "classic"})
        selection.save(self.co, Selection(games.parse("0.35b"), "original"))
        out, _ = self.overview()
        self.assertRegex(line(out, "Original client:"), r"0\.35, Classic classes$")
        self.assertIn("built for 0.35: run daoc game switch 0.35b", out)

    def test_new_client_not_available_on_035(self):
        out, _ = self.overview()
        self.assertRegex(line(out, "New client:"), r"not available for 0\.35$")
        selection.save(self.co, Selection(games.parse("0.36b"), "new"))
        out, _ = self.overview()
        self.assertRegex(line(out, "New client:"), r"not installed$")
        self.co.new_client_root.mkdir(parents=True)
        pins.record_installed(self.co, "new_client", {"version": "0.36c", "game": "0.36b"})
        out, _ = self.overview()
        self.assertRegex(line(out, "New client:"), r"0\.36c, for 0\.36b$")

    def test_pin_rows_for_selected_version(self):
        selection.save(self.co, Selection(games.parse("0.36b"), "original"))
        out, _ = self.overview()
        for label in ("server@0.36", "original_client@0.36", "new_client@0.36", "graphics"):
            pin_row(out, label)
        self.assertNotIn("server@0.35", out)


if __name__ == "__main__":
    unittest.main()
