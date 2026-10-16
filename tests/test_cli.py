"""Router, exit codes, Checkout paths, proc helpers and the sh launcher."""
import argparse
import io
import json
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import cli, proc
from daoc_cli.checkout import Checkout, wine_env
from daoc_cli.errors import DaocError

VISIBLE_GROUPS = ("server", "client", "admin", "progress", "graphics", "self-install")


def fake_group(name, handler):
    """A group module whose one parser runs handler."""
    def register(groups):
        groups.add_parser(name, help=f"fake {name}").set_defaults(func=handler)
    return SimpleNamespace(register=register)


def with_group(name, module):
    """GROUPS with name's entry swapped for module (appended when absent)."""
    entries = [(n, module if n == name else m) for n, m in cli.GROUPS]
    if name not in dict(cli.GROUPS):
        entries.append((name, module))
    return mock.patch.object(cli, "GROUPS", tuple(entries))


class HelpAndUsageTest(unittest.TestCase):
    def test_no_args_prints_the_overview_and_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli([], make_checkout(tmp))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("daoc checkout "), out)
        self.assertIn("Commands:", out)
        self.assertEqual(err, "")

    def test_help_lists_groups_but_not_dev(self):
        code, out, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        for group in VISIBLE_GROUPS:
            self.assertRegex(out, rf"(?m)^\s+{group}\s")
        self.assertIn("{" + ",".join(VISIBLE_GROUPS) + "}", out)
        self.assertNotRegex(out, r"\bdev\b")
        self.assertNotIn("SUPPRESS", out)

    def test_client_help_lists_mtld3d(self):
        code, out, _ = run_cli(["client", "--help"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^\s+mtld3d\s+use our mtld3d build \(fork\) or the Wine's own")
        args = cli.build_parser()[0].parse_args(["client", "mtld3d", "stock", "--wine", "arm64"])
        self.assertEqual((args.choice, args.wine), ("stock", "arm64"))

    def test_unknown_group_is_usage_error(self):
        code, out, err = run_cli(["nosuch"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("usage: daoc", err)

    def test_group_without_action_is_usage_error(self):
        code, out, err = run_cli(["server"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("daoc server: error: an action is required", err)

    def test_dev_is_hidden_but_parses(self):
        code, out, _ = run_cli(["dev", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: daoc dev", out)


class DispatchTest(unittest.TestCase):
    def test_handler_gets_args_and_the_checkout(self):
        seen = {}

        def handler(args, checkout):
            seen["group"], seen["root"] = args.group, checkout.root
            return 0

        with tempfile.TemporaryDirectory() as tmp, with_group("probe", fake_group("probe", handler)):
            root = make_checkout(tmp)
            code, _, _ = run_cli(["probe"], checkout_root=root)
            self.assertEqual(code, 0)
            self.assertEqual(seen, {"group": "probe", "root": root.resolve()})

    def test_handler_exit_code_is_returned(self):
        with with_group("probe", fake_group("probe", lambda args, checkout: 3)):
            self.assertEqual(run_cli(["probe"])[0], 3)

    def test_daoc_error_prints_message_and_its_code(self):
        def handler(args, checkout):
            raise DaocError("refused", code=2)

        with with_group("probe", fake_group("probe", handler)):
            code, out, err = run_cli(["probe"])
        self.assertEqual((code, out, err), (2, "", "daoc: refused\n"))

    def test_version_prints_the_checkouts_release_and_runs_no_group(self):
        ran = []
        with tempfile.TemporaryDirectory() as tmp, \
                with_group("probe", fake_group("probe", lambda args, checkout: ran.append(1) or 0)):
            root = make_checkout(tmp)
            (root / "version.txt").write_text("1.2.3\n")
            self.assertEqual(run_cli(["--version"], root), (0, "daoc 1.2.3\n", ""))
            self.assertEqual(run_cli(["--version", "probe"], root), (0, "daoc 1.2.3\n", ""))
        self.assertEqual(ran, [])

    def test_version_without_version_txt_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_checkout(tmp)
            (root / "version.txt").unlink()
            code, out, err = run_cli(["--version"], root)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("version.txt is missing", err)

    def test_keyboard_interrupt_exits_130(self):
        def handler(args, checkout):
            raise KeyboardInterrupt

        with with_group("probe", fake_group("probe", handler)):
            self.assertEqual(run_cli(["probe"])[0], 130)

    def test_passthrough_argv_is_untouched(self):
        seen = {}

        def handler(args, checkout):
            seen["argv"] = args.passthrough
            return 0

        raw = ["--", "-x", "--help", "bots", "list", "--verbose"]
        with with_group("admin", fake_group("admin", handler)):
            self.assertEqual(run_cli(["admin"] + raw)[0], 0)
            self.assertEqual(seen["argv"], raw)
            self.assertEqual(run_cli(["admin"])[0], 0)
            self.assertEqual(seen["argv"], [])
            code, out, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertEqual(len(re.findall(r"(?m)^\s+admin\s", out)), 1)

    def test_non_passthrough_groups_get_none(self):
        seen = {}

        def handler(args, checkout):
            seen["argv"] = args.passthrough
            return 0

        with with_group("server", fake_group("server", handler)):
            self.assertEqual(run_cli(["server"])[0], 0)
        self.assertIsNone(seen["argv"])

    def test_hidden_module_group_stays_out_of_help(self):
        def register(groups):
            groups.add_parser("dev", help=argparse.SUPPRESS).set_defaults(func=lambda a, c: 0)

        with with_group("dev", SimpleNamespace(register=register)):
            self.assertEqual(run_cli(["dev"])[0], 0)
            _, out, _ = run_cli(["--help"])
        self.assertNotRegex(out, r"\bdev\b")


class CheckoutTest(unittest.TestCase):
    def test_paths_derive_from_root(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            os.environ.pop("DAOC_WINE_HOME", None)
            os.environ.pop("DAOC_WINEPREFIX", None)
            root = make_checkout(tmp).resolve()
            co = Checkout(root)
            self.assertEqual(co.root, root)
            self.assertEqual(co.server_dir, root / "server/dist/daoc-server")
            self.assertEqual(co.client_root, root / "dist/OfflineDAoC")
            self.assertEqual(co.app_dir, root / "dist/OfflineDAoC/runtime/client-opendaoc/app")
            self.assertEqual(co.wine_home, root / "dist/wine")
            self.assertEqual(co.prefix, root / "dist/prefix")
            self.assertEqual(co.launcher_app, root / "dist/DAoCLauncher.app")
            self.assertEqual(co.graphics_src, root / "upstream/graphics")
            self.assertEqual(co.downloads, root / "downloads")
            self.assertEqual(co.state, root / ".daoc")
            self.assertEqual(co.manifest["schema"], 1)

    def test_default_root_is_this_checkout(self):
        self.assertEqual(Checkout().root, Path(__file__).resolve().parents[1])

    def test_wine_overrides_resolve_against_cwd(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            os.environ["DAOC_WINE_HOME"] = "w"
            os.environ["DAOC_WINEPREFIX"] = "/abs/prefix"
            try:
                os.chdir(tmp)
                co = Checkout(make_checkout(tmp))
                here = Path(os.getcwd())
            finally:
                os.chdir(cwd)
        self.assertEqual(co.wine_home, here / "w")
        self.assertEqual(co.prefix, Path("/abs/prefix"))

    def test_missing_manifest_is_a_daoc_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DaocError):
                Checkout(tmp).manifest

    def test_unreadable_flavour_record_is_a_daoc_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            co = Checkout(tmp)
            co.flavour_file.mkdir(parents=True)  # reading it raises IsADirectoryError
            with self.assertRaises(DaocError) as cm:
                co.flavour
        self.assertIn(f"cannot read {co.flavour_file}", cm.exception.msg)
        self.assertIn("daoc client install --wine rosetta", cm.exception.msg)

    def test_only_an_arm64_wine_gets_its_library_path(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            os.environ.pop("DYLD_FALLBACK_LIBRARY_PATH", None)
            arm64, rosetta = Path(tmp) / "arm64", Path(tmp) / "rosetta"
            (arm64 / "lib" / "wine" / "aarch64-unix").mkdir(parents=True)
            (rosetta / "lib" / "wine" / "x86_64-unix").mkdir(parents=True)
            env = wine_env(arm64, Path("/p"))
            self.assertEqual((env["WINEPREFIX"], env["DYLD_FALLBACK_LIBRARY_PATH"]),
                             ("/p", str(arm64 / "ext" / "lib")))
            self.assertNotIn("DYLD_FALLBACK_LIBRARY_PATH", wine_env(rosetta, Path("/p")))


class ProcTest(unittest.TestCase):
    SCRIPT = "echo out; echo err >&2; exit {}"

    def test_quiet_success_captures_and_prints_nothing(self):
        err = io.StringIO()
        with redirect_stderr(err):
            result = proc.run(["/bin/sh", "-c", self.SCRIPT.format(0)])
        self.assertEqual((result.stdout, result.stderr, err.getvalue()), ("out\n", "err\n", ""))

    def test_quiet_failure_replays_to_stderr_and_raises(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(DaocError) as caught:
            proc.run(["/bin/sh", "-c", self.SCRIPT.format(3)])
        self.assertEqual(err.getvalue(), "out\nerr\n")
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("sh failed (exit 3)", caught.exception.msg)

    def test_unchecked_failure_returns_quietly(self):
        err = io.StringIO()
        with redirect_stderr(err):
            result = proc.run(["/bin/sh", "-c", self.SCRIPT.format(4)], check=False)
        self.assertEqual((result.returncode, err.getvalue()), (4, ""))

    def test_argv_is_never_a_shell_string(self):
        with self.assertRaises(TypeError):
            proc.run("echo hi")
        with self.assertRaises(DaocError):
            proc.run(["/nonexistent/tool"])


PROBE_MAIN = """\
import json, os, sys
import daoc_cli
print(json.dumps({"cwd": os.getcwd(), "pythonpath": os.environ.get("PYTHONPATH"),
                  "package": os.path.dirname(os.path.abspath(daoc_cli.__file__)),
                  "argv": sys.argv[1:]}))
"""


@unittest.skipUnless(os.access("/usr/bin/python3", os.X_OK), "needs /usr/bin/python3")
class LauncherTest(unittest.TestCase):
    """The sh launcher, run as a subprocess the way users run it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_checkout(self.tmp)
        self.caller = self.tmp / "caller"
        self.caller.mkdir()
        self.stubs = path_stubs(self.tmp, {
            "xcode-select": f"echo {shlex.quote(str(self.tmp))}",
            "xcode-select-fails": "exit 2",
            "xcode-select-gone": "echo /nonexistent/CommandLineTools",
        })
        self.env = dict(os.environ)
        self.env.pop("PYTHONPATH", None)
        self.env["DAOC_XCODE_SELECT"] = str(self.stubs / "xcode-select")

    def launch(self, argv, launcher=None, **env):
        return subprocess.run(
            [str(launcher or self.root / "daoc")] + list(argv), cwd=str(self.caller),
            env=dict(self.env, **env), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=60,
        )

    def probe(self, argv=(), launcher=None, **env):
        (self.root / "daoc_cli" / "__main__.py").write_text(PROBE_MAIN)
        result = self.launch(argv, launcher, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_help_and_usage_error_from_another_directory(self):
        result = self.launch(["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("usage: daoc"), result.stdout)
        result = self.launch(["nosuch"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage: daoc", result.stderr)

    def test_keeps_the_caller_cwd_and_argv(self):
        seen = self.probe(["--", "-x", "a b", "--help"])
        self.assertEqual(seen["cwd"], str(self.caller))
        self.assertEqual(seen["argv"], ["--", "-x", "a b", "--help"])
        self.assertEqual(seen["package"], str(self.root / "daoc_cli"))
        self.assertEqual(stub_calls(self.stubs), [["xcode-select", "-p"]])

    def test_imports_its_own_package_not_one_in_cwd_or_pythonpath(self):
        for decoy in (self.caller / "daoc_cli", self.tmp / "pp" / "daoc_cli"):
            decoy.mkdir(parents=True)
            (decoy / "__init__.py").write_text("")
            (decoy / "__main__.py").write_text("print('DECOY')\n")
        seen = self.probe(PYTHONPATH=str(self.tmp / "pp"))
        self.assertEqual(seen["package"], str(self.root / "daoc_cli"))

    def test_pythonpath_is_not_set_for_children(self):
        self.assertIsNone(self.probe()["pythonpath"])
        self.assertEqual(self.probe(PYTHONPATH="/caller/path")["pythonpath"], "/caller/path")

    def test_follows_a_symlink_to_the_launcher(self):
        link_dir = self.tmp / "bin"
        link_dir.mkdir()
        (link_dir / "daoc").symlink_to(self.root / "daoc")
        seen = self.probe(launcher=link_dir / "daoc")
        self.assertEqual(seen["package"], str(self.root / "daoc_cli"))

    def test_missing_command_line_tools_exit_1(self):
        for stub in ("xcode-select-fails", "xcode-select-gone"):
            result = self.launch(["--help"], DAOC_XCODE_SELECT=str(self.stubs / stub))
            self.assertEqual(result.returncode, 1, stub)
            self.assertEqual(result.stdout, "")
            self.assertIn("xcode-select --install", result.stderr)


if __name__ == "__main__":
    unittest.main()
