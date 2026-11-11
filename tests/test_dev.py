"""`daoc dev ship-pins` and `ship-prebuilt`: output with and without Local pins."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import edition_sql, pins, server
from daoc_cli.checkout import Checkout

NEW_REF = "0123456789abcdef0123456789abcdef01234567"


class ShipPinsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_checkout(self._tmp.name)
        self.manifest = self.root / "manifest.json"

    def test_nothing_to_ship(self):
        before = self.manifest.read_bytes()
        code, out, err = run_cli(["dev", "ship-pins"], self.root)
        self.assertEqual((code, out, err), (0, "nothing to ship\n", ""))
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_local_pin_is_shipped_and_cleared(self):
        co = Checkout(self.root)
        pins.set_local(co, "server", dict(pins.shipped(co, "server", "0.35"), ref=NEW_REF), "0.35")
        code, out, err = run_cli(["dev", "ship-pins"], self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, f"shipped server@0.35 {NEW_REF[:12]}\nnow commit manifest.json\n")
        self.assertEqual(json.loads(self.manifest.read_text())["versions"]["0.35"]["server"]["ref"], NEW_REF)
        self.assertFalse((self.root / ".daoc" / "pins.json").exists())
        self.assertEqual(run_cli(["dev", "ship-pins"], self.root)[1], "nothing to ship\n")

    def test_dev_stays_out_of_help(self):
        code, out, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertNotRegex(out, r"\bdev\b")
        code, out, _ = run_cli(["dev", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("ship-pins", out)
        self.assertIn("e2e", out)


class ShipPrebuiltTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = make_checkout(self.tmp)
        self.ref = pins.shipped(Checkout(self.root), "server", "0.37")["ref"]

    def test_writes_url_size_and_hash(self):
        tarball = self.tmp / server.prebuilt_name("0.37", self.ref)
        tarball.write_bytes(b"tarball")
        url = ("https://github.com/trozzelle/OfflineDAoC-macOS/releases/download/"
               f"server-0.37-{self.ref[:12]}/{tarball.name}")
        code, out, err = run_cli(["dev", "ship-prebuilt", "0.37", str(tarball), url], self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, f"shipped server@0.37 prebuilt {tarball.name}\nnow commit manifest.json\n")
        entry = json.loads((self.root / "manifest.json").read_text())["versions"]["0.37"]["server"]
        self.assertEqual(entry["prebuilt"], {"url": url, "bytes": 7,
                                             "sha256": hashlib.sha256(b"tarball").hexdigest()})
        self.assertEqual(entry["ref"], self.ref)

    def test_refuses_a_tarball_of_another_commit_or_a_mismatched_url(self):
        other = self.tmp / server.prebuilt_name("0.37", "f" * 40)
        other.write_bytes(b"x")
        self.assertEqual(run_cli(["dev", "ship-prebuilt", "0.37", str(other),
                                  f"https://x/{other.name}"], self.root)[0], 2)
        right = self.tmp / server.prebuilt_name("0.37", self.ref)
        right.write_bytes(b"x")
        self.assertEqual(run_cli(["dev", "ship-prebuilt", "0.37", str(right),
                                  "https://x/another-name.tar.xz"], self.root)[0], 2)


class EditionSqlTest(unittest.TestCase):
    def test_version_argument_reaches_generate(self):
        # A positional named `version` would shadow `daoc --version` and print the daoc release.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(edition_sql, "generate") as generate:
            code, out, err = run_cli(["dev", "edition-sql", "0.36"], make_checkout(tmp))
        self.assertEqual((code, out), (0, ""), err)
        self.assertEqual(generate.call_args[0][1], "0.36")


if __name__ == "__main__":
    unittest.main()
