"""daoc self-install: the ~/.local/bin/daoc wrapper and the PATH offer, against a temp HOME."""
import io
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import self_install


class TtyInput(io.StringIO):
    def isatty(self):
        return True


class SelfInstallTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.root = make_checkout(self.tmp)
        self.wrapper = self.home / ".local" / "bin" / "daoc"
        self.env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin"}

    def install(self, stdin=None, env=None):
        with mock.patch("sys.stdin", stdin or io.StringIO("")):
            return run_cli(["self-install"], checkout_root=self.root, env=dict(self.env, **(env or {})))

    def test_wrapper_content_and_mode(self):
        code, out, err = self.install()
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertIn(str(self.wrapper), err)
        text = self.wrapper.read_text()
        self.assertTrue(text.startswith("#!/bin/sh\n" + self_install.MARKER + "\n"))
        self.assertIn(f"CHECKOUT={self.root}\n", text)
        self.assertIn('exec "$CHECKOUT/daoc" "$@"', text)
        self.assertEqual(stat.S_IMODE(self.wrapper.stat().st_mode), 0o755)
        self.assertEqual(subprocess.run(["/bin/sh", "-n", str(self.wrapper)]).returncode, 0)

    def test_path_with_spaces_is_quoted(self):
        text = self_install.wrapper_text(Path("/a b/it's"))
        self.assertIn("CHECKOUT='/a b/it'\"'\"'s'\n", text)

    def test_rerun_is_idempotent(self):
        self.assertEqual(self.install()[0], 0)
        first = self.wrapper.read_text()
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(self.wrapper.read_text(), first)
        self.assertEqual(sorted(p.name for p in self.wrapper.parent.iterdir()), ["daoc"])

    def test_foreign_file_is_refused(self):
        self.wrapper.parent.mkdir(parents=True)
        self.wrapper.write_text("#!/bin/sh\necho mine\n")
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn(str(self.wrapper), err)
        self.assertEqual(self.wrapper.read_text(), "#!/bin/sh\necho mine\n")

    def test_wrapper_exits_127_after_checkout_moves(self):
        self.assertEqual(self.install()[0], 0)
        self.root.rename(self.tmp / "moved")
        result = subprocess.run([str(self.wrapper), "--help"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=30)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr,
            f"daoc: checkout {self.root} is gone (moved or deleted); "
            "run ./daoc self-install from its new location\n")

    def test_non_tty_prints_path_line_and_leaves_zprofile(self):
        code, out, err = self.install()
        self.assertEqual(code, 0)
        self.assertIn(self_install.PATH_LINE, err)
        self.assertFalse((self.home / ".zprofile").exists())

    def test_on_path_says_nothing_about_path(self):
        code, _, err = self.install(env={"PATH": f"{self.wrapper.parent}:/usr/bin"})
        self.assertEqual(code, 0)
        self.assertNotIn(self_install.PATH_LINE, err)

    def test_tty_yes_appends_once(self):
        profile = self.home / ".zprofile"
        profile.write_text("export FOO=1")
        self.assertEqual(self.install(TtyInput("y\n"))[0], 0)
        self.assertEqual(self.install(TtyInput("y\n"))[0], 0)
        self.assertEqual(profile.read_text(), "export FOO=1\n" + self_install.PATH_LINE + "\n")

    def test_tty_default_is_no(self):
        code, _, err = self.install(TtyInput("\n"))
        self.assertEqual(code, 0)
        self.assertIn("[y/N]", err)
        self.assertFalse((self.home / ".zprofile").exists())


if __name__ == "__main__":
    unittest.main()
