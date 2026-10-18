"""daoc server / admin / progress: passthrough argv, missing install, install build step."""
import io
import os
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import errors, games, keychain, proc, selection, server
from daoc_cli.checkout import Checkout
from daoc_cli.selection import Selection


class Exec(Exception):
    pass


class PassthroughTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_checkout(self.tmp.name)
        self.co = Checkout(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self):
        self.co.server_dir.mkdir(parents=True)
        for name in ("daoc-server.sh", "daoc-admin", "daoc-progress"):
            p = self.co.server_dir / name
            p.write_text("#!/bin/sh\n")
            p.chmod(0o755)

    def execv_calls(self, argv):
        calls = []

        def fake(args, cwd=None, env=None):
            calls.append((list(map(str, args)), cwd))
            raise Exec

        with mock.patch.object(proc, "execv", fake):
            with self.assertRaises(Exec):
                run_cli(argv, self.root)
        return calls

    def test_admin_and_progress_argv_untouched(self):
        self.install()
        args = ["--", "-x", "two words", "--help", ""]
        for group, tool in (("admin", "daoc-admin"), ("progress", "daoc-progress")):
            calls = self.execv_calls([group, *args])
            self.assertEqual(calls, [([str(self.co.server_dir / tool), *args], None)])

    def test_server_actions_exec_script_in_server_dir(self):
        self.install()
        script = str(self.co.server_dir / "daoc-server.sh")
        for argv, want in ((["start", "--console"], ["start", "--console"]),
                           (["start"], ["start"]), (["stop"], ["stop"]), (["status"], ["status"])):
            calls = self.execv_calls(["server", *argv])
            self.assertEqual(calls, [([script, *want], self.co.server_dir)])

    def test_missing_install_exits_1(self):
        for argv in (["admin", "help"], ["progress"], ["server", "status"], ["server", "start"]):
            code, out, err = run_cli(argv, self.root)
            self.assertEqual(code, 1, argv)
            self.assertEqual(err, "daoc: no Server install; run daoc server install\n")

    def test_running(self):
        self.assertIs(server.running(self.co), False)
        self.install()
        (self.co.server_dir / "daoc-server.sh").write_text("#!/bin/sh\necho 'running (pid 7)'\n")
        self.assertIs(server.running(self.co), True)
        (self.co.server_dir / "daoc-server.sh").write_text("#!/bin/sh\nexit 3\n")
        self.assertIsNone(server.running(self.co))

    def test_set_edition_writes_config(self):
        server.set_edition(self.co, "sluaghbinder")
        self.assertEqual((self.co.server_dir / "config" / "edition").read_text(), "sluaghbinder\n")
        server.set_edition(self.co, "classic")
        self.assertEqual((self.co.server_dir / "config" / "edition").read_text(), "classic\n")
        with self.assertRaises(errors.DaocError):
            server.set_edition(self.co, "both")


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(make_checkout(self.tmp.name)))
        self.co = Checkout(self.root)
        self.ref = self.co.manifest["versions"]["0.35"]["server"]["ref"]
        src = self.root / "upstream" / "server"
        (src / ".git").mkdir(parents=True)
        tools = self.root / "server" / "tools"
        tools.mkdir(parents=True)
        for version in ("0.35", "0.36"):
            (self.root / "server" / "patches" / version).mkdir(parents=True)
            (self.root / "server" / "patches" / version / f"{version}.patch").write_text("")
        # What `git archive` of the navmesh paths yields.
        fixture = Path(self.tmp.name) / "archive"
        (fixture / "world" / "navmesh").mkdir(parents=True)
        (fixture / "world" / "navmesh" / "zone000.nav.xz").write_bytes(b"xz")
        (fixture / "world" / "navmesh-manifest.sha256").write_text("x  zone000.nav\n")
        build_env = Path(self.tmp.name) / "stubs" / "build.env"
        self.stubs = path_stubs(self.tmp.name, {
            "git": (f'[ "$3" = rev-parse ] && echo "${{HEAD_SHA:-{self.ref}}}"\n'
                    'if [ "$3" = archive ]; then\n'
                    '  for a; do case $a in --output=*) out=${a#--output=};; esac; done\n'
                    f'  /usr/bin/tar -cf "$out" -C {fixture} world\n'
                    'fi\nexit 0'),
            "cmake": "exit 0",
            "setup-dotnet.sh": "exit 0",
            "build-release.sh": (f'm=$DAOC_NAVMESH_SRC/world/navmesh-manifest.sha256; [ -f "$m" ] && m=present\n'
                                 f'echo "$PWD|$DAOC_SOURCE_REPO|$DAOC_GAME_VERSION|$m" >> {build_env}'),
        })
        self.build_env = build_env
        for name in ("setup-dotnet.sh", "build-release.sh"):
            os.symlink(self.stubs / name, tools / name)
        self.env = {"PATH": f"{self.stubs}:/usr/bin:/bin"}

    def tearDown(self):
        self.tmp.cleanup()

    def select(self, game):
        selection.save(self.co, Selection(games.parse(game), "original"))
        self.ref = self.co.manifest["versions"][games.parse(game).version]["server"]["ref"]
        self.env["HEAD_SHA"] = self.ref

    def git_calls(self, verb):
        return [c for c in stub_calls(self.stubs) if c[0] == "git" and c[3] == verb]

    def test_install_builds_with_resolved_cwd_and_pinned_repo(self):
        code, _, err = run_cli(["server", "install"], self.root,
                               env=dict(self.env, DAOC_SOURCE_REPO="/elsewhere"))
        self.assertEqual(code, 0, err)
        names = [c[0] for c in stub_calls(self.stubs)]
        self.assertNotIn("clone", [c[1] for c in stub_calls(self.stubs) if c[0] == "git"])
        self.assertEqual([n for n in names if n != "git"][-2:], ["setup-dotnet.sh", "build-release.sh"])
        self.assertEqual(stub_calls(self.stubs)[-1][1:], [])
        env = self.build_env.read_text().strip()
        self.assertEqual(env, f"{self.root}|{self.root / 'upstream' / 'server'}|0.35|present")

    def test_install_passes_version_and_navmesh_src(self):
        self.select("0.36b")
        code, _, err = run_cli(["server", "install"], self.root, env=self.env)
        self.assertEqual(code, 0, err)
        self.assertTrue(self.build_env.read_text().strip().endswith("|0.36|present"))
        archive = self.git_calls("archive")
        self.assertEqual(len(archive), 1)
        self.assertIn(self.ref, archive[0])
        self.assertEqual(archive[0][-2:], ["world/navmesh", "world/navmesh-manifest.sha256"])

    def test_patch_precheck_uses_version_dir(self):
        self.select("0.36")
        code, _, err = run_cli(["server", "install"], self.root, env=self.env)
        self.assertEqual(code, 0, err)
        (apply,) = self.git_calls("apply")
        self.assertEqual(apply[4:], ["--check", str(self.root / "server" / "patches" / "0.36" / "0.36.patch")])

    def test_035_exports_navmesh_from_navmesh_ref(self):
        navmesh_ref = self.co.manifest["versions"]["0.35"]["server"]["navmesh_ref"]
        code, _, err = run_cli(["server", "install"], self.root, env=self.env)
        self.assertEqual(code, 0, err)
        self.assertIn(["git", "-C", str(self.root / "upstream" / "server"), "fetch", "--quiet",
                       "origin", navmesh_ref], stub_calls(self.stubs))
        (archive,) = self.git_calls("archive")
        self.assertIn(navmesh_ref, archive)
        self.assertNotIn(self.ref, archive)

    def test_missing_patch_dir_is_error(self):
        shutil.rmtree(self.root / "server" / "patches" / "0.35")
        code, _, err = run_cli(["server", "install"], self.root, env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("no macOS patches for game version 0.35", err)
        self.assertFalse(self.build_env.exists())

    def test_verbose_passes_through(self):
        code, _, err = run_cli(["server", "install", "--verbose"], self.root, env=self.env)
        self.assertEqual(code, 0, err)
        self.assertEqual(stub_calls(self.stubs)[-1], ["build-release.sh", "--verbose"])

    def test_wrong_head_fails(self):
        code, _, err = run_cli(["server", "install"], self.root, env=dict(self.env, HEAD_SHA="deadbeef"))
        self.assertEqual(code, 1)
        self.assertIn("upstream HEAD deadbeef", err)


class Tty(io.StringIO):
    def isatty(self):
        return True


class PromptTest(unittest.TestCase):
    """Prompts go to stderr; stdout stays data only."""

    def ask(self, fn, answer):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", Tty(answer)), mock.patch("sys.stdout", out), \
                mock.patch("sys.stderr", err):
            result = fn()
        return result, out.getvalue(), err.getvalue()

    def test_ask(self):
        yes, out, err = self.ask(lambda: errors.ask("Stop?"), "y\n")
        self.assertTrue(yes)
        self.assertEqual(out, "")
        self.assertIn("Stop? [y/N] ", err)

    def test_keychain_save_interactive(self):
        done = subprocess.CompletedProcess([], 0, "secret\n", "")
        with mock.patch.object(keychain.proc, "run", return_value=done) as run:
            _, out, err = self.ask(keychain.save_interactive, "alice\n")
        self.assertEqual(out, "")
        self.assertIn("Game account name: ", err)
        adds = [c[0][0] for c in run.call_args_list if c[0][0][1] == "add-generic-password"]
        self.assertIn("alice", adds[0])



if __name__ == "__main__":
    unittest.main()
