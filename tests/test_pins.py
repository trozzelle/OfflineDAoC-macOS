"""Local pins per game version: precedence, lapse, ship() and atomic writes."""
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
SLUAGHBINDER_DLL = "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b"


class PinsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_checkout(self._tmp.name)
        self.co = Checkout(self.root)
        self.store = self.root / ".daoc" / "pins.json"

    def manifest(self):
        return json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))

    def change_shipped(self, group, version=None, **fields):
        """Rewrite manifest.json as a git pull would, then drop the cached copy."""
        data = self.manifest()
        (data["versions"][version] if version else data)[group].update(fields)
        (self.root / "manifest.json").write_text(json.dumps(data, indent=2))
        del self.co.manifest

    def effective(self, group, version=None):
        err = io.StringIO()
        with redirect_stderr(err):
            pin = pins.effective(self.co, group, version)
        return pin, err.getvalue()

    def test_shipped_is_the_versions_entry_without_note(self):
        entry = self.manifest()["versions"]["0.36"]["server"]
        shipped = pins.shipped(self.co, "server", "0.36")
        self.assertNotIn("note", shipped)
        self.assertEqual(shipped, {k: v for k, v in entry.items() if k != "note"})
        self.assertEqual(pins.shipped(self.co, "graphics")["repo"], self.manifest()["graphics"]["repo"])

    def test_versioned_group_needs_version(self):
        for group in pins.VERSIONED:
            with self.subTest(group=group):
                with self.assertRaises(DaocError) as cm:
                    pins.shipped(self.co, group)
                self.assertIn("needs a game version", cm.exception.msg)

    def test_version_without_new_client(self):
        with self.assertRaises(DaocError) as cm:
            pins.shipped(self.co, "new_client", "0.35")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("0.35 has no new client", cm.exception.msg)

    def test_no_local_pin_means_shipped(self):
        self.assertIsNone(pins.local(self.co, "server", "0.36"))
        self.assertEqual(self.effective("server", "0.36"), (pins.shipped(self.co, "server", "0.36"), ""))
        self.assertFalse(self.store.exists())

    def test_local_pin_is_per_version(self):
        shipped = pins.shipped(self.co, "server", "0.36")
        pins.set_local(self.co, "server", dict(shipped, ref=NEW_REF), "0.36")
        self.assertEqual(self.effective("server", "0.36")[0]["ref"], NEW_REF)
        self.assertEqual(self.effective("server", "0.35")[0], pins.shipped(self.co, "server", "0.35"))
        self.change_shipped("server", "0.36", ref=OTHER_REF)
        pin, err = self.effective("server", "0.36")
        self.assertEqual(pin["ref"], OTHER_REF)
        self.assertEqual(
            err, f"daoc: Local server@0.36 pin {NEW_REF[:12]} lapsed; Shipped pin {OTHER_REF[:12]} applies\n")
        self.assertFalse(self.store.exists())

    def test_store_entry_records_version(self):
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server", "0.36"), ref=NEW_REF), "0.36")
        entry = json.loads(self.store.read_text())[0]
        self.assertEqual((entry["group"], entry["version"]), ("server", "0.36"))
        self.assertEqual(entry["replaces"], pins.shipped(self.co, "server", "0.36"))
        self.assertRegex(entry["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_graphics_local_pin_has_no_version(self):
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        entry = json.loads(self.store.read_text())[0]
        self.assertNotIn("version", entry)
        self.assertEqual(self.effective("graphics")[0]["ref"], NEW_REF)

    def test_legacy_client_entry_dropped_with_notice(self):
        self.store.parent.mkdir()
        legacy = {"group": "client", "pin": {"version": "0.36"}, "replaces": {"version": "0.35b"},
                  "at": "2026-10-11T12:00:00Z"}
        graphics = {"group": "graphics", "pin": dict(pins.shipped(self.co, "graphics"), ref=NEW_REF),
                    "replaces": pins.shipped(self.co, "graphics"), "at": "2026-10-11T12:00:00Z"}
        self.store.write_text(json.dumps([legacy, graphics]))
        pin, err = self.effective("original_client", "0.35")
        self.assertEqual(pin, pins.shipped(self.co, "original_client", "0.35"))
        self.assertEqual(err, "daoc: Local client pin from before game versions dropped\n")
        self.assertEqual([e["group"] for e in json.loads(self.store.read_text())], ["graphics"])
        self.assertEqual(self.effective("graphics"), (graphics["pin"], ""))

    def test_ship_writes_under_versions(self):
        before = self.manifest()
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server", "0.36"), ref=NEW_REF), "0.36")
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=OTHER_REF))
        self.assertEqual(pins.ship(self.co), ["server@0.36", "graphics"])
        after = self.manifest()
        self.assertEqual(after["versions"]["0.36"]["server"]["ref"], NEW_REF)
        self.assertEqual(after["versions"]["0.36"]["server"]["note"],
                         before["versions"]["0.36"]["server"]["note"])
        self.assertEqual(list(after["versions"]["0.36"]["server"]), list(before["versions"]["0.36"]["server"]))
        self.assertEqual(after["versions"]["0.35"], before["versions"]["0.35"])
        self.assertEqual(after["graphics"]["ref"], OTHER_REF)
        self.assertEqual(list(after), list(before))
        self.assertFalse(self.store.exists())
        self.assertEqual(pins.shipped(self.co, "server", "0.36")["ref"], NEW_REF)  # re-read

    def test_ship_keeps_layout_of_unchanged_lines(self):
        original = (self.root / "manifest.json").read_text(encoding="utf-8")
        pins.set_local(self.co, "graphics", dict(pins.shipped(self.co, "graphics"), ref=NEW_REF))
        pins.ship(self.co)
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
        pins.set_local(self.co, "server", dict(pins.shipped(self.co, "server", "0.36"), ref=NEW_REF), "0.36")
        self.change_shipped("server", "0.36", ref=OTHER_REF)
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(pins.ship(self.co), [])
        self.assertIn("lapsed", err.getvalue())
        self.assertEqual(self.manifest()["versions"]["0.36"]["server"]["ref"], OTHER_REF)

    def test_writes_leave_no_tmp_files_and_keep_manifest_mode(self):
        path = self.root / "manifest.json"
        path.chmod(0o644)
        shipped = pins.shipped(self.co, "server", "0.36")
        pins.set_local(self.co, "server", dict(shipped, ref=NEW_REF), "0.36")
        pins.set_local(self.co, "server", dict(shipped, ref=OTHER_REF), "0.36")
        self.assertEqual(len(json.loads(self.store.read_text())), 1)
        pins.ship(self.co)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_original_client_record_path(self):
        self.co.client_root.mkdir(parents=True)
        pins.record_installed(self.co, "original_client", {"version": "0.36b", "note": "x"})
        record = json.loads((self.root / "dist" / "OfflineDAoC" / pins.INSTALLED).read_text())
        self.assertEqual(record, {"version": "0.36b"})
        self.assertEqual(pins.installed(self.co, "original_client"), {"version": "0.36b"})

    def test_new_client_record_path(self):
        self.co.new_client_root.mkdir(parents=True)
        pins.record_installed(self.co, "new_client", {"version": "0.36c"})
        self.assertTrue((self.root / "dist" / "new-client" / pins.INSTALLED).is_file())

    def test_legacy_install_maps_to_035b(self):
        # A record-less install from the old tooling; game.dll stands in with the
        # pristine hash by patching sha256 on the module.
        self.co.app_dir.mkdir(parents=True)
        (self.co.app_dir / "game.dll").write_bytes(b"pristine")
        original = pins.sha256
        pins.sha256 = lambda path: SLUAGHBINDER_DLL
        self.addCleanup(setattr, pins, "sha256", original)
        pin = pins.shipped(self.co, "original_client", "0.35")
        self.assertEqual(pins.built_from(self.co, "original_client", pin), ("0.35b", True))
        record = pins.installed(self.co, "original_client")
        self.assertEqual((record["version"], record["edition"]), ("0.35b", "sluaghbinder"))

    def test_bad_group_and_bad_store_are_errors(self):
        with self.assertRaises(DaocError):
            pins.effective(self.co, "wine")
        with self.assertRaises(DaocError):
            pins.effective(self.co, "client", "0.35")
        self.store.parent.mkdir()
        self.store.write_text("{not json")
        with self.assertRaises(DaocError) as cm:
            pins.effective(self.co, "server", "0.36")
        self.assertIn(str(self.store), cm.exception.msg)


if __name__ == "__main__":
    unittest.main()
