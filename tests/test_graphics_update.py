"""daoc graphics update: the contract check and the Local graphics pin.

A local bare repo stands in for the graphics remote, with one minimal fake
daoc-gfx project per commit; resolve_latest is patched to name a commit of it,
so nothing touches the network or the real graphics project.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import pins, updates
from daoc_cli.checkout import Checkout

STOCK_LINE = 'export WINEDLLOVERRIDES="${DAOC_DLL_OVERRIDES:-d3d9,dxgi=b}"'
STATUS = {
    "schema": 1,
    "patches": {"retina": "off", "srgb": "off", "textures": "not installed", "anisotropy": "off"},
    "anisotropy_level": None,
    "mtld3d_conf": "none",
    "textures": {"components": [], "pending": None},
}

# A fake daoc-gfx; @NAME@ markers are filled in by project().
DAOC_GFX = '''#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

p = argparse.ArgumentParser(prog="daoc-gfx")
for option in @OPTIONS@:
    p.add_argument(option, required=option == "--app")
commands = p.add_subparsers(dest="command")
status = commands.add_parser("status")
if @JSON_FLAG@:
    status.add_argument("--json", action="store_true")
commands.add_parser("select")
textures = commands.add_parser("textures").add_subparsers(dest="action")
if @EXPORT@:
    textures.add_parser("export").add_argument("dir")
install = textures.add_parser("install")
install.add_argument("archives", nargs="*")
if @FROM_DIR@:
    install.add_argument("--from-dir")
args = p.parse_args()
if not (Path(args.app) / "game.dll").is_file():
    sys.exit(f"{args.app} is not a DAoC client app folder (no game.dll)")
if not (Path(args.launcher) / "Contents" / "MacOS" / "launch").is_file():
    sys.exit(f"no launcher at {args.launcher}")
if args.command == "status" and args.json:
    print(json.dumps(@STATUS@))
'''

TESTS = '''import unittest


class FakeTest(unittest.TestCase):
    def test_passes(self):
        self.assertTrue(@PASS@)

    @unittest.skip("no cc")
    def test_skips(self):
        pass
'''


def project(tests_pass=True, options=("--app", "--wine", "--prefix", "--launcher"),
            stock_line=STOCK_LINE, json_flag=True, status=STATUS, export=True, from_dir=True):
    gfx = DAOC_GFX
    for marker, value in (("@OPTIONS@", repr(list(options))), ("@JSON_FLAG@", repr(json_flag)),
                          ("@EXPORT@", repr(export)), ("@FROM_DIR@", repr(from_dir)),
                          ("@STATUS@", repr(status))):
        gfx = gfx.replace(marker, value)
    return {
        "daoc-gfx": gfx,
        "daoc_gfx/__init__.py": "",
        "daoc_gfx/anisotropy.py": f"STOCK_LINE = {stock_line!r}\n",
        "tests/test_fake.py": TESTS.replace("@PASS@", repr(tests_pass)),
    }


# One contract-breaking commit per check: (commit, the check its error names).
BROKEN = {
    "tests": (dict(tests_pass=False), "tests"),
    "help": (dict(options=("--app", "--wine", "--launcher")), "daoc-gfx --help"),
    "stock": (dict(stock_line='export WINEDLLOVERRIDES="d3d9=b"'), "STOCK_LINE"),
    "no-json": (dict(json_flag=False), "status --json"),
    "schema": (dict(status=dict(STATUS, schema=2)), "status --json"),
    "keys": (dict(status={k: v for k, v in STATUS.items() if k != "textures"}), "status --json"),
    "export": (dict(export=False), "textures --help"),
    "from-dir": (dict(from_dir=False), "textures install --help"),
}


def _git(*args: str, cwd=None) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


class GraphicsUpdateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        work = Path(tmp.name).resolve() / "work"
        work.mkdir()
        _git("init", "--quiet", cwd=work)
        cls.commits = {}
        for name, kwargs in [("base", {}), ("good", {})] + [(k, v[0]) for k, v in BROKEN.items()]:
            for rel, text in project(**kwargs).items():
                path = work / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            (work / "daoc-gfx").chmod(0o755)
            _git("add", "-A", cwd=work)
            _git("commit", "--quiet", "--allow-empty", "-m", name, cwd=work)
            cls.commits[name] = _git("rev-parse", "HEAD", cwd=work)
        cls.bare = Path(tmp.name).resolve() / "graphics.git"
        _git("clone", "--quiet", "--bare", str(work), str(cls.bare))

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(Path(tmp.name).resolve())
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["graphics"]["repo"] = str(self.bare)
        manifest["graphics"]["ref"] = self.commits["base"]
        path.write_text(json.dumps(manifest))
        self.launch = self.root / "client" / "DAoCLauncher.app" / "Contents" / "MacOS" / "launch"
        self.launch.parent.mkdir(parents=True)
        self.launch.write_text(f"#!/bin/sh\nif true; then\n    {STOCK_LINE}\nfi\n")
        self.co = Checkout(self.root)

    def update(self, ref: str):
        latest = {"repo": str(self.bare), "ref": ref}
        with mock.patch.object(updates, "resolve_latest", return_value=latest) as resolve:
            result = run_cli(["graphics", "update"], self.root)
        resolve.assert_called_once()
        return result

    def test_passing_commit_sets_the_local_pin(self) -> None:
        good = self.commits["good"]
        code, out, err = self.update(good)
        self.assertEqual(code, 0, err)
        self.assertEqual(pins.local(self.co, "graphics"), {"repo": str(self.bare), "ref": good})
        self.assertIn(f"graphics pin -> {good[:12]}", out)
        self.assertIn("the next daoc graphics … call checks it out", out)
        self.assertIn(f"== graphics tests pass at {good[:12]}", err)
        self.assertIn("skipped 'no cc'", err)
        self.assertIn(f"== daoc-gfx machine interface matches at {good[:12]}", err)
        self.assertFalse((self.root / "upstream").exists())

    def test_already_at_the_effective_pin(self) -> None:
        base = self.commits["base"]
        code, out, err = self.update(base)
        self.assertEqual((code, out), (0, f"graphics already at {base[:12]}\n"))
        self.assertFalse((self.root / ".daoc" / "pins.json").exists())

    def test_already_at_the_local_pin(self) -> None:
        good = self.commits["good"]
        pins.set_local(self.co, "graphics", {"repo": str(self.bare), "ref": good})
        before = (self.root / ".daoc" / "pins.json").read_bytes()
        code, out, err = self.update(good)
        self.assertEqual((code, out), (0, f"graphics already at {good[:12]}\n"))
        self.assertEqual((self.root / ".daoc" / "pins.json").read_bytes(), before)

    def assert_refused(self, ref: str, check: str) -> str:
        code, out, err = self.update(ref)
        self.assertEqual(code, 1, err)
        self.assertIn(f"graphics contract check '{check}' fails at {ref[:12]}", err)
        self.assertIn("pin unchanged", err)
        self.assertIsNone(pins.local(self.co, "graphics"))
        self.assertFalse((self.root / ".daoc" / "pins.json").exists())
        self.assertNotIn("graphics pin ->", out)
        return err

    def test_each_failing_check_leaves_the_pin_and_names_the_check(self) -> None:
        for name, (_, check) in BROKEN.items():
            with self.subTest(name):
                self.assert_refused(self.commits[name], check)

    def test_failing_tests_are_replayed(self) -> None:
        err = self.assert_refused(self.commits["tests"], "tests")
        self.assertIn("FAILED", err)

    def test_missing_option_is_named(self) -> None:
        err = self.assert_refused(self.commits["help"], "daoc-gfx --help")
        self.assertIn("no longer lists --prefix", err)

    def test_launcher_line_must_occur_once(self) -> None:
        self.launch.write_text(f"{STOCK_LINE}\n{STOCK_LINE}\n")
        err = self.assert_refused(self.commits["good"], "STOCK_LINE")
        self.assertIn("occurs 2 times", err)

    def test_status_json_missing_keys_are_named(self) -> None:
        err = self.assert_refused(self.commits["keys"], "status --json")
        self.assertIn("it has no textures", err)


if __name__ == "__main__":
    unittest.main()
