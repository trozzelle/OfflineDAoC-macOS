"""daoc status --json: the app's view of the install, offline and without git."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import keychain


class StatusJsonTest(unittest.TestCase):
    def test_a_fresh_data_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_checkout(tmp)
            data = Path(tmp).resolve() / "data"
            stubs = path_stubs(tmp, {"git": "exit 0"})
            with mock.patch.object(keychain, "saved", return_value=None):
                code, out, err = run_cli(["status", "--json"], root,
                                         env={"DAOC_DATA": str(data), "PATH": f"{stubs}:/usr/bin:/bin"})
            calls = stub_calls(stubs)
            default = json.loads((root / "manifest.json").read_text())["default"]["game"]
        self.assertEqual(code, 0, err)
        status = json.loads(out)
        self.assertEqual(status["schema"], 1)
        self.assertEqual(status["home"], str(data))
        self.assertEqual(status["game"]["name"], default)
        self.assertEqual(status["installed"], {"server": False, "original_client": False, "new_client": False})
        self.assertEqual(status["server"], {"running": False, "detail": "stopped"})
        self.assertIsNone(status["switching_to"])
        self.assertIsNone(status["client_running"])
        self.assertIsNone(status["account_saved"])
        self.assertIsNone(status["save"])
        self.assertEqual(calls, [])

    def test_the_original_client_is_installed_only_once_client_install_finished(self):
        # client install swaps dist/OfflineDAoC in first and records the flavour last.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_checkout(tmp)
            data = Path(tmp).resolve() / "data"
            dist = data / "dist"
            stubs = path_stubs(tmp, {"git": "exit 0"})
            env = {"DAOC_DATA": str(data), "PATH": f"{stubs}:/usr/bin:/bin"}

            def original_client():
                with mock.patch.object(keychain, "saved", return_value=None):
                    code, out, err = run_cli(["status", "--json"], root, env=env)
                self.assertEqual(code, 0, err)
                return json.loads(out)["installed"]["original_client"]

            (dist / "OfflineDAoC").mkdir(parents=True)
            self.assertFalse(original_client())
            (dist / "DAoCLauncher.app").mkdir()
            self.assertFalse(original_client())
            (dist / ".wine-flavour").write_text("rosetta\n")
            self.assertTrue(original_client())
            (dist / "OfflineDAoC").rmdir()
            self.assertFalse(original_client())

    def test_status_prints_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli(["status"], make_checkout(tmp))
        self.assertEqual(code, 2)
        self.assertIn("daoc status needs --json", err)


if __name__ == "__main__":
    unittest.main()
