"""`daoc dev ship-pins`: output with and without Local pins."""
import json
import tempfile
import unittest

from tests.support import make_checkout, run_cli

from daoc_cli import pins
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


if __name__ == "__main__":
    unittest.main()
