"""Client patch: Proven builds only, the .orig pristine copy, idempotent re-runs."""
import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

import tests.support  # noqa: F401  (puts the Checkout root on sys.path)

from daoc_cli import client_patch
from daoc_cli.errors import DaocError

SPEC = client_patch.V0_35B


def pristine_bytes() -> bytes:
    """A synthetic DLL holding the spec's original bytes at its offsets."""
    data = bytearray(b"\xcc" * 0x12000)
    for e in SPEC:
        data[e.offset:e.offset + len(e.original)] = e.original
    return bytes(data)


def patched_bytes() -> bytes:
    data = bytearray(pristine_bytes())
    for e in SPEC:
        data[e.offset:e.offset + len(e.patched)] = e.patched
    return bytes(data)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dll = Path(self.tmp.name) / "game.dll"
        self.orig = Path(self.tmp.name) / "game.dll.orig"
        self.proven = {sha(pristine_bytes()): SPEC}

    def tearDown(self):
        self.tmp.cleanup()

    def patch(self, proven=None):
        err = io.StringIO()
        with redirect_stderr(err):
            changed = client_patch.patch(self.dll, self.proven if proven is None else proven)
        return changed, err.getvalue()

    def test_seeded_with_the_current_pristine_build(self):
        self.assertIs(client_patch.PROVEN_BUILDS[
            "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b"], SPEC)

    def test_classic_build_is_proven_with_same_spec(self):
        # OfflineDAoC 0.35/0.36 Classic classes edition: the three sites byte-checked identical.
        self.assertIs(client_patch.PROVEN_BUILDS[
            "f55ed6b068e22ce8e1106871c2fad6ee10c18390bbb8b5dc772219ad8c8b83bb"], SPEC)

    def test_proven_build_is_patched_and_pristine_kept(self):
        self.dll.write_bytes(pristine_bytes())
        changed, _ = self.patch()
        self.assertTrue(changed)
        self.assertEqual(self.dll.read_bytes(), patched_bytes())
        self.assertEqual(self.orig.read_bytes(), pristine_bytes())

    def test_unproven_hash_is_refused_and_untouched(self):
        data = pristine_bytes() + b"x"
        self.dll.write_bytes(data)
        with self.assertRaises(DaocError) as cm:
            self.patch()
        self.assertIn(sha(data), cm.exception.msg)
        self.assertIn("not a Proven build", cm.exception.msg)
        self.assertEqual(self.dll.read_bytes(), data)
        self.assertFalse(self.orig.exists())

    def test_default_set_refuses_the_synthetic_build(self):
        self.dll.write_bytes(pristine_bytes())
        with self.assertRaises(DaocError):
            self.patch(proven=client_patch.PROVEN_BUILDS)
        self.assertEqual(self.dll.read_bytes(), pristine_bytes())

    def test_unproven_orig_is_refused(self):
        self.orig.write_bytes(pristine_bytes() + b"x")
        self.dll.write_bytes(patched_bytes())
        with self.assertRaises(DaocError) as cm:
            self.patch()
        self.assertIn("not a Proven build", cm.exception.msg)
        self.assertEqual(self.dll.read_bytes(), patched_bytes())

    def test_already_patched_with_orig_is_a_noop(self):
        self.dll.write_bytes(pristine_bytes())
        self.patch()
        before = self.dll.stat().st_mtime_ns
        changed, err = self.patch()
        self.assertFalse(changed)
        self.assertIn("already patched", err)
        self.assertEqual(self.dll.stat().st_mtime_ns, before)
        self.assertEqual(self.dll.read_bytes(), patched_bytes())
        self.assertEqual(self.orig.read_bytes(), pristine_bytes())

    def test_orig_present_repatches_a_restored_dll(self):
        self.orig.write_bytes(pristine_bytes())
        self.dll.write_bytes(pristine_bytes())
        changed, _ = self.patch()
        self.assertTrue(changed)
        self.assertEqual(self.dll.read_bytes(), patched_bytes())

    def test_patched_without_orig_gets_its_pristine_copy_back(self):
        self.dll.write_bytes(patched_bytes())
        changed, err = self.patch()
        self.assertFalse(changed)
        self.assertIn("already patched", err)
        self.assertEqual(self.orig.read_bytes(), pristine_bytes())
        self.assertEqual(self.dll.read_bytes(), patched_bytes())

    def test_install_patched_by_an_older_spec_gets_the_new_edits(self):
        # A game.dll patched before the Shared-section edit existed, no .orig.
        older = bytearray(pristine_bytes())
        for e in client_patch.NO_ENCRYPTION:
            older[e.offset:e.offset + len(e.patched)] = e.patched
        self.dll.write_bytes(bytes(older))
        changed, _ = self.patch()
        self.assertTrue(changed)
        self.assertEqual(self.orig.read_bytes(), pristine_bytes())
        self.assertEqual(self.dll.read_bytes(), patched_bytes())

    def test_patched_regions_over_an_unproven_base_are_refused(self):
        data = patched_bytes() + b"x"
        self.dll.write_bytes(data)
        with self.assertRaises(DaocError):
            self.patch()
        self.assertEqual(self.dll.read_bytes(), data)
        self.assertFalse(self.orig.exists())

    def test_unexpected_bytes_in_a_proven_hash_are_refused(self):
        data = bytearray(pristine_bytes())
        data[SPEC[1].offset] = 0x07
        self.dll.write_bytes(bytes(data))
        with self.assertRaises(DaocError) as cm:
            self.patch(proven={sha(bytes(data)): SPEC})
        self.assertIn("unexpected", cm.exception.msg)
        self.assertEqual(self.dll.read_bytes(), bytes(data))
        self.assertFalse(self.orig.exists())

    def test_missing_dll(self):
        with self.assertRaises(DaocError):
            self.patch()


if __name__ == "__main__":
    unittest.main()
