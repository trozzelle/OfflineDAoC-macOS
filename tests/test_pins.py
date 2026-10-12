"""Local pins: precedence, lapse, ship() and atomic writes."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr

from tests.support import make_checkout

from daoc_cli import pins
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

NEW_REF = "0123456789abcdef0123456789abcdef01234567"
OTHER_REF = "fedcba9876543210fedcba9876543210fedcba98"


class PinsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_checkout(self._tmp.name)
        self.co = Checkout(self.root)
        self.store = self.root / ".daoc" / "pins.json"

    def manifest(self):
        return json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))

    def change_shipped(self, group, **fields):
        """Rewrite manifest.json as a git pull would, then drop the cached copy."""
        data = self.manifest()
        data[group].update(fields)
        (self.root / "manifest.json").write_text(json.dumps(data, indent=2))
        del self.co.manifest

    def effective(self, group):
        err = io.StringIO()
        with redirect_stderr(err):
            pin = pins.effective(self.co, group)
        return pin, err.getvalue()

    def test_shipped_is_the_manifest_entry_without_note(self):
        entry = self.manifest()["graphics"]
        shipped = pins.shipped(self.co, "graphics")
        self.assertNotIn("note", shipped)
        self.assertEqual(shipped, {k: v for k, v in entry.items() if k != "note"})

    def test_no_local_pin_means_shipped(self):
        self.assertIsNone(pins.local(self.co, "server"))
        self.assertEqual(self.effective("server"), (pins.shipped(self.co, "server"), ""))
        self.assertFalse(self.store.exists())

    def test_local_pin_wins_while_replaces_matches(self):
        shipped = pins.shipped(self.co, "graphics")
        pins.set_local(self.co, "graphics", dict(shipped, ref=NEW_REF))
        entry = json.loads(self.store.read_text())[0]
        self.assertEqual(entry["group"], "graphics")
        self.assertEqual(entry["replaces"], shipped)
        self.assertRegex(entry["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        pin, err = self.effective("graphics")
        self.assertEqual(pin["ref"], NEW_REF)
        self.assertEqual(err, "")
        self.assertEqual(pins.local(self.co, "graphics")["ref"], NEW_REF)
        self.assertEqual(self.effective("server")[0], pins.shipped(self.co, "server"))

    def test_local_pin_lapses_when_shipped_pin_changes(self):
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server"), ref=NEW_REF))
        self.change_shipped("server", ref=OTHER_REF)
        self.assertIsNone(pins.local(self.co, "server"))
        self.assertTrue(self.store.exists(), "local() must not drop the entry")
        pin, err = self.effective("server")
        self.assertEqual(pin["ref"], OTHER_REF)
        self.assertEqual(
            err, f"daoc: Local server pin {NEW_REF[:12]} lapsed; Shipped pin {OTHER_REF[:12]} applies\n")
        self.assertFalse(self.store.exists())
        self.assertEqual(self.effective("server"), (pin, ""))

    def test_lapse_keeps_other_groups_and_names_client_by_version(self):
        pins.set_local(self.co, "client", dict(pins.shipped(self.co, "client"), version="0.36"))
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        self.change_shipped("client", version="0.35c")
        pin, err = self.effective("client")
        self.assertEqual(pin["version"], "0.35c")
        self.assertEqual(err, "daoc: Local client pin 0.36 lapsed; Shipped pin 0.35c applies\n")
        self.assertEqual(self.effective("graphics")[0]["ref"], NEW_REF)

    def test_ship_round_trip(self):
        original = (self.root / "manifest.json").read_text(encoding="utf-8")
        before = self.manifest()
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        new_client = dict(pins.shipped(self.co, "client"), version="0.36", game_dll_sha256="ab" * 32)
        pins.set_local(self.co, "client", new_client)
        self.assertIsNotNone(self.co.manifest)  # cached before ship
        self.assertEqual(pins.ship(self.co), ["client", "graphics"])

        after = self.manifest()
        self.assertEqual(list(after), list(before))
        for group in (g for g, v in before.items() if isinstance(v, dict)):
            self.assertEqual(list(after[group]), list(before[group]), group)
            self.assertEqual(after[group].get("note"), before[group].get("note"), group)
        self.assertEqual(after["graphics"]["ref"], NEW_REF)
        self.assertEqual(after["client"]["version"], "0.36")
        self.assertEqual(after["client"]["parts"], before["client"]["parts"])
        self.assertEqual(after["server"], before["server"])
        self.assertEqual(after["wine"], before["wine"])
        self.assertEqual(after["schema"], before["schema"])
        self.assertFalse(self.store.exists())
        self.assertEqual(self.co.manifest["graphics"]["ref"], NEW_REF)  # re-read
        self.assertEqual(pins.shipped(self.co, "graphics")["ref"], NEW_REF)

        # Unchanged lines keep the file's own layout (one-line part objects).
        new_text = (self.root / "manifest.json").read_text(encoding="utf-8")
        self.assertEqual(new_text.endswith("\n"), original.endswith("\n"))
        for line in original.splitlines():
            if '"name": "OfflineDAoC' in line:
                self.assertIn(line, new_text.splitlines())

    def test_ship_without_local_pins_leaves_manifest_alone(self):
        path = self.root / "manifest.json"
        original = path.read_bytes()
        self.assertEqual(pins.ship(self.co), [])
        self.assertEqual(path.read_bytes(), original)

    def test_ship_drops_a_lapsed_pin_instead_of_writing_it(self):
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server"), ref=NEW_REF))
        self.change_shipped("server", ref=OTHER_REF)
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(pins.ship(self.co), [])
        self.assertIn("lapsed", err.getvalue())
        self.assertEqual(self.manifest()["server"]["ref"], OTHER_REF)

    def test_writes_leave_no_tmp_files_and_keep_manifest_mode(self):
        path = self.root / "manifest.json"
        path.chmod(0o644)
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server"), ref=NEW_REF))
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server"), ref=OTHER_REF))
        self.assertEqual(len(json.loads(self.store.read_text())), 1)
        pins.ship(self.co)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_bad_group_and_bad_store_are_errors(self):
        with self.assertRaises(DaocError):
            pins.effective(self.co, "wine")
        self.store.parent.mkdir()
        self.store.write_text("{not json")
        with self.assertRaises(DaocError) as cm:
            pins.effective(self.co, "server")
        self.assertIn(str(self.store), cm.exception.msg)


if __name__ == "__main__":
    unittest.main()
