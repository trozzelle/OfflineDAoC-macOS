"""daoc server / admin / progress: passthrough argv, missing install, install build step."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import proc, server
from daoc_cli.checkout import Checkout


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


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(make_checkout(self.tmp.name)))
        self.co = Checkout(self.root)
        self.ref = self.co.manifest["server"]["ref"]
        src = self.root / "upstream" / "server"
        (src / ".git").mkdir(parents=True)
        tools = self.root / "server" / "tools"
        tools.mkdir(parents=True)
        (self.root / "server" / "patches").mkdir()
        (self.root / "server" / "patches" / "a.patch").write_text("")
        self.stubs = path_stubs(self.tmp.name, {
            "git": f'[ "$3" = rev-parse ] && echo {self.ref}; exit 0',
            "cmake": "exit 0",
            "setup-dotnet.sh": "exit 0",
            "build-release.sh": f'echo "$PWD|$DAOC_SOURCE_REPO" >> {Path(self.tmp.name) / "stubs" / "build.env"}',
        })
        for name in ("setup-dotnet.sh", "build-release.sh"):
            os.symlink(self.stubs / name, tools / name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_builds_with_resolved_cwd_and_pinned_repo(self):
        code, _, err = run_cli(["server", "install"], self.root,
                               env={"PATH": f"{self.stubs}:/usr/bin:/bin",
                                    "DAOC_SOURCE_REPO": "/elsewhere"})
        self.assertEqual(code, 0, err)
        names = [c[0] for c in stub_calls(self.stubs)]
        self.assertNotIn("clone", [c[1] for c in stub_calls(self.stubs) if c[0] == "git"])
        self.assertEqual(names[-2:], ["setup-dotnet.sh", "build-release.sh"])
        self.assertEqual(stub_calls(self.stubs)[-1][1:], [])
        env = (self.stubs / "build.env").read_text().strip()
        self.assertEqual(env, f"{self.root}|{self.root / 'upstream' / 'server'}")

    def test_verbose_passes_through(self):
        code, _, err = run_cli(["server", "install", "--verbose"], self.root,
                               env={"PATH": f"{self.stubs}:/usr/bin:/bin"})
        self.assertEqual(code, 0, err)
        self.assertEqual(stub_calls(self.stubs)[-1], ["build-release.sh", "--verbose"])

    def test_wrong_head_fails(self):
        (self.stubs / "git").write_text('#!/bin/sh\n[ "$3" = rev-parse ] && echo deadbeef; exit 0\n')
        code, _, err = run_cli(["server", "install"], self.root,
                               env={"PATH": f"{self.stubs}:/usr/bin:/bin"})
        self.assertEqual(code, 1)
        self.assertIn("upstream HEAD deadbeef", err)


if __name__ == "__main__":
    unittest.main()
