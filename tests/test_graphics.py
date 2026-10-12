"""daoc graphics: pinned checkout of the graphics project and the daoc-gfx argv.

A local bare repo stands in for the graphics remote; nothing touches the network.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import graphics, proc


class Exec(Exception):
    pass


def _git(*args: str, cwd=None) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


class GraphicsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.root = make_checkout(self.tmp)
        work = self.tmp / "work"
        work.mkdir()
        _git("init", "--quiet", cwd=work)
        (work / "daoc-gfx").write_text("print('gfx')\n")
        _git("add", ".", cwd=work)
        _git("commit", "--quiet", "-m", "one", cwd=work)
        self.first = _git("rev-parse", "HEAD", cwd=work)
        (work / "daoc-gfx").write_text("print('gfx2')\n")
        _git("commit", "--quiet", "-am", "two", cwd=work)
        self.second = _git("rev-parse", "HEAD", cwd=work)
        self.bare = self.tmp / "graphics.git"
        _git("clone", "--quiet", "--bare", str(work), str(self.bare))
        self.pin(self.second)
        app = self.root / "dist" / "OfflineDAoC" / "runtime" / "client-opendaoc" / "app"
        app.mkdir(parents=True)
        (app / "game.dll").write_bytes(b"")
        self.app = app
        self.src = self.root / "upstream" / "graphics"
        patcher = mock.patch.object(proc, "execv", side_effect=self._exec)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.argv = None

    def _exec(self, argv, **kwargs):
        self.argv = list(argv)
        self.exec_kwargs = kwargs
        raise Exec()

    def pin(self, ref: str) -> None:
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["graphics"]["repo"] = str(self.bare)
        manifest["graphics"]["ref"] = ref
        path.write_text(json.dumps(manifest))

    def run_gfx(self, *args: str, env=None):
        env = dict({"DAOC_WINE_HOME": None, "DAOC_WINEPREFIX": None}, **(env or {}))
        try:
            return run_cli(["graphics", *args], self.root, env=env)
        except Exec:
            return None

    def test_clone_and_argv_select_default(self) -> None:
        self.assertIsNone(self.run_gfx())
        self.assertEqual(_git("-C", str(self.src), "rev-parse", "HEAD"), self.second)
        self.assertEqual(self.argv, [
            "/usr/bin/python3", str(self.src / "daoc-gfx"),
            "--app", str(self.app),
            "--wine", str(self.root / "dist" / "wine"),
            "--prefix", str(self.root / "dist" / "prefix"),
            "select",
        ])
        self.assertNotIn("cwd", self.exec_kwargs)

    def test_args_passed_untouched(self) -> None:
        self.run_gfx("enable", "--archives", "x", "--", "-y")
        self.assertEqual(self.argv[-5:], ["enable", "--archives", "x", "--", "-y"])

    def test_pin_mismatch_checked_out(self) -> None:
        self.run_gfx("status")
        self.pin(self.first)
        self.assertIsNone(self.run_gfx("status"))
        self.assertEqual(_git("-C", str(self.src), "rev-parse", "HEAD"), self.first)

    def test_dirty_refused(self) -> None:
        self.run_gfx("status")
        (self.src / "DIRTY").write_text("")
        self.argv = None
        code, out, err = self.run_gfx("status")
        self.assertEqual(code, 1)
        self.assertIn("has local changes", err)
        self.assertIn("remove that folder to re-clone the pinned commit", err)
        self.assertIsNone(self.argv)

    def test_missing_client(self) -> None:
        (self.app / "game.dll").unlink()
        code, out, err = self.run_gfx("status")
        self.assertEqual(code, 1)
        self.assertIn(f"no client in {self.app} — run daoc client install", err)
        self.assertFalse(self.src.exists())

    def test_update_reserved(self) -> None:
        code, out, err = self.run_gfx("update", "now")
        self.assertEqual(code, 2)
        self.assertIsNone(self.argv)
        self.assertFalse(self.src.exists())

    def test_relative_env_resolved_against_cwd(self) -> None:
        cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        self.run_gfx("status", env={"DAOC_WINE_HOME": "w", "DAOC_WINEPREFIX": "p/x"})
        self.assertEqual(self.argv[5], str(self.tmp / "w"))
        self.assertEqual(self.argv[7], str(self.tmp / "p" / "x"))
        self.assertEqual(os.getcwd(), str(self.tmp))


if __name__ == "__main__":
    unittest.main()
