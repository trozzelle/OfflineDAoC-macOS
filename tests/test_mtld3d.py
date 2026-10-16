"""daoc_cli.mtld3d: the fork bundle fetch and its install into either Wine,
on fake Wine trees and a fake bundle in temp dirs (no network, no dist/)."""
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import tests.support  # noqa: F401  (puts the Checkout root on sys.path)

from daoc_cli import mtld3d
from daoc_cli.errors import DaocError

VERSION = "v0.13.0-daoc.1"
MARKER = b"Wine builtin DLL"
# The Rosetta Wine ships no x86_64-windows/mtld3d.dll: its stock is "absent".
ABSENT = {"rosetta": {"lib/wine/d3d9/mtld3d/x86_64-windows/mtld3d.dll"}, "arm64": set()}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def member_bytes(member: str, tag: str = "fork") -> bytes:
    data = f"{tag} {member}\n".encode()
    if member.startswith("wine/") and member.endswith(".dll"):
        data += MARKER
    return data


def bundle_files(tag: str = "fork"):
    members = {m for rows in mtld3d.TARGETS.values() for m, _ in rows}
    return {m: member_bytes(m, tag) for m in sorted(members)}


def write_tree(root: Path, files) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def stock_files(flavour: str, tag: str = "stock"):
    return {t: f"{tag} {t}\n".encode() for _, t in mtld3d.TARGETS[flavour]
            if t not in ABSENT[flavour]}


def snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


class Quiet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        quiet = redirect_stderr(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def tearDown(self):
        self.tmp.cleanup()

    def wine(self, flavour: str, name: str = None) -> Path:
        home = self.root / (name or f"wine-{flavour}")
        write_tree(home, stock_files(flavour))
        write_tree(home, {"bin/wine": b"#!/bin/sh\n"})
        return home

    def bundle(self, files=None, name: str = "bundle") -> Path:
        path = self.root / name
        write_tree(path, files if files is not None else bundle_files())
        return path


class ApplyTest(Quiet):
    def test_apply_installs_every_target(self):
        for flavour in ("rosetta", "arm64"):
            with self.subTest(flavour=flavour):
                home, bundle = self.wine(flavour), self.bundle(name=f"bundle-{flavour}")
                mtld3d.apply(home, flavour, bundle, VERSION)
                for member, target in mtld3d.TARGETS[flavour]:
                    self.assertEqual((home / target).read_bytes(), (bundle / member).read_bytes(),
                                     target)
                record = json.loads((home / ".daoc-mtld3d.json").read_text())
                self.assertEqual(record["choice"], "fork")
                self.assertEqual(record["version"], VERSION)
                self.assertEqual(mtld3d.state(home, flavour), f"fork {VERSION}")

    def test_arm64_targets_are_the_ruled_ones(self):
        self.assertEqual(mtld3d.TARGETS["arm64"], [
            ("native/i386-windows/d3d9.dll", "lib/hadron/d3d9/i386/d3d9.dll"),
            ("wine/i386-windows/mtld3d.dll", "lib/wine/i386-windows/mtld3d.dll"),
            ("wine/i386-windows/mtld3d.dll", "lib/hadron/d3d9/markers/syswow64/mtld3d.dll"),
            ("wine/aarch64-unix/mtld3d.so", "lib/wine/aarch64-unix/mtld3d.so"),
        ])
        self.assertTrue(all(t.startswith("lib/wine/d3d9/mtld3d/")
                            for _, t in mtld3d.TARGETS["rosetta"]))

    def test_restore_brings_back_stock_bytes(self):
        for flavour in ("rosetta", "arm64"):
            with self.subTest(flavour=flavour):
                home, bundle = self.wine(flavour), self.bundle(name=f"bundle-{flavour}")
                before = {t: (home / t).read_bytes() if (home / t).exists() else None
                          for _, t in mtld3d.TARGETS[flavour]}
                mtld3d.apply(home, flavour, bundle, VERSION)
                mtld3d.restore_stock(home, flavour)
                for target, data in before.items():
                    if data is None:
                        self.assertFalse((home / target).exists(), target)
                    else:
                        self.assertEqual((home / target).read_bytes(), data, target)
                self.assertEqual(mtld3d.state(home, flavour), "stock")
                self.assertEqual(mtld3d.choice(home), "stock")
                # And back to the fork: the saved stock is kept, not overwritten.
                mtld3d.apply(home, flavour, bundle, VERSION)
                mtld3d.restore_stock(home, flavour)
                for target, data in before.items():
                    if data is not None:
                        self.assertEqual((home / target).read_bytes(), data, target)

    def test_restore_refuses_a_damaged_stock_copy(self):
        home, bundle = self.wine("arm64"), self.bundle()
        mtld3d.apply(home, "arm64", bundle, VERSION)
        target = mtld3d.TARGETS["arm64"][0][1]
        (home / ".daoc-mtld3d" / "stock" / target).write_bytes(b"damaged")
        with self.assertRaises(DaocError):
            mtld3d.restore_stock(home, "arm64")

    def test_state_reports_fork_stock_and_mixed(self):
        home, bundle = self.wine("rosetta"), self.bundle()
        self.assertEqual(mtld3d.state(home, "rosetta"), "stock")
        mtld3d.apply(home, "rosetta", bundle, VERSION)
        self.assertEqual(mtld3d.state(home, "rosetta"), f"fork {VERSION}")
        second = mtld3d.TARGETS["rosetta"][1][1]
        (home / second).write_bytes(b"something else")
        self.assertEqual(mtld3d.state(home, "rosetta"), f"mixed: {second}")
        mtld3d.restore_stock(home, "rosetta")
        self.assertEqual(mtld3d.state(home, "rosetta"), "stock")
        first = mtld3d.TARGETS["rosetta"][0][1]
        (home / first).write_bytes(b"something else")
        self.assertEqual(mtld3d.state(home, "rosetta"), f"mixed: {first}")

    def test_install_resumes_after_partial_copy(self):
        home, bundle = self.wine("arm64"), self.bundle()
        stock = {t: (home / t).read_bytes() for _, t in mtld3d.TARGETS["arm64"]}
        real_put = mtld3d._put
        written = []

        def failing_put(src, dest):
            real_put(src, dest)
            if ".daoc-mtld3d" not in dest.parts:
                written.append(dest)
                raise OSError("disk went away")

        with mock.patch.object(mtld3d, "_put", failing_put):
            with self.assertRaises(OSError):
                mtld3d.apply(home, "arm64", bundle, VERSION)
        self.assertEqual(len(written), 1)
        self.assertTrue(mtld3d.state(home, "arm64").startswith("mixed: "))
        mtld3d.apply(home, "arm64", bundle, VERSION)
        self.assertEqual(mtld3d.state(home, "arm64"), f"fork {VERSION}")
        # The target copied before the failure still restores to its stock bytes.
        mtld3d.restore_stock(home, "arm64")
        for target, data in stock.items():
            self.assertEqual((home / target).read_bytes(), data, target)

    def test_wine_reinstall_resaves_stock(self):
        old, bundle = self.wine("rosetta", "old"), self.bundle()
        mtld3d.apply(old, "rosetta", bundle, VERSION)
        old_record = json.loads((old / ".daoc-mtld3d.json").read_text())
        fresh = self.root / "fresh"
        new_stock = stock_files("rosetta", "new stock")
        write_tree(fresh, new_stock)
        (fresh / ".daoc-mtld3d.json").write_text(json.dumps(old_record))
        mtld3d.apply(fresh, "rosetta", bundle, VERSION)
        record = json.loads((fresh / ".daoc-mtld3d.json").read_text())
        for target, data in new_stock.items():
            self.assertEqual(record["stock"][target], sha(data), target)
            self.assertNotEqual(record["stock"][target], old_record["stock"][target])
        mtld3d.restore_stock(fresh, "rosetta")
        for target, data in new_stock.items():
            self.assertEqual((fresh / target).read_bytes(), data, target)

    def test_apply_never_writes_unmarked_pe_on_rosetta(self):
        home = self.wine("rosetta")
        files = bundle_files()
        files["wine/x86_64-windows/mtld3d.dll"] = b"MZ native, no marker"
        bundle = self.bundle(files)
        before = snapshot(home)
        with self.assertRaises(DaocError) as cm:
            mtld3d.apply(home, "rosetta", bundle, VERSION)
        self.assertIn("wine/x86_64-windows/mtld3d.dll", cm.exception.msg)
        self.assertEqual(snapshot(home), before)

    def test_arm64_native_d3d9_needs_no_marker(self):
        home = self.wine("arm64")
        files = bundle_files()
        self.assertNotIn(MARKER, files["native/i386-windows/d3d9.dll"])
        mtld3d.apply(home, "arm64", self.bundle(files), VERSION)
        self.assertEqual(mtld3d.state(home, "arm64"), f"fork {VERSION}")

    def test_missing_member_touches_nothing(self):
        home = self.wine("arm64")
        files = bundle_files()
        del files["wine/aarch64-unix/mtld3d.so"]
        before = snapshot(home)
        with self.assertRaises(DaocError):
            mtld3d.apply(home, "arm64", self.bundle(files), VERSION)
        self.assertEqual(snapshot(home), before)

    def test_choice_defaults_to_fork_and_is_set(self):
        home = self.wine("arm64")
        self.assertEqual(mtld3d.choice(home), "fork")
        mtld3d.set_choice(home, "stock")
        self.assertEqual(mtld3d.choice(home), "stock")
        mtld3d.apply(home, "arm64", self.bundle(), VERSION)
        self.assertEqual(mtld3d.choice(home), "fork")
        with self.assertRaises(DaocError):
            mtld3d.set_choice(home, "maybe")


def tarball(files) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FetchTest(Quiet):
    URL = "https://example.invalid/mtld3d.tar.xz"

    def checkout(self, data: bytes, members=None, sha256=None):
        pin = {"url": self.URL, "asset": "mtld3d.tar.xz", "sha256": sha256 or sha(data),
               "version": VERSION, "note": "test"}
        if members is not None:
            pin["members"] = members
        return SimpleNamespace(manifest={"mtld3d": pin}, downloads=self.root / "downloads")

    def fake(self, data: bytes):
        urls = []

        def fetch(url, dest):
            urls.append(url)
            dest.write_bytes(data)
        return fetch, urls

    def test_fetch_bundle_downloads_verifies_and_extracts(self):
        files = bundle_files()
        data = tarball(files)
        checkout = self.checkout(data, {m: sha(b) for m, b in files.items()})
        fetch, urls = self.fake(data)
        out = mtld3d.fetch_bundle(checkout, fetch_url=fetch)
        self.assertEqual(urls, [self.URL])
        self.assertEqual(out, checkout.downloads / f"mtld3d-{VERSION}")
        self.assertEqual(snapshot(out), files)
        # A second call reuses the verified extraction without downloading.
        self.assertEqual(mtld3d.fetch_bundle(checkout, fetch_url=fetch), out)
        self.assertEqual(urls, [self.URL])
        # A damaged extraction is redone from the cached tarball.
        (out / "wine/aarch64-unix/mtld3d.so").write_bytes(b"damaged")
        self.assertEqual(mtld3d.fetch_bundle(checkout, fetch_url=fetch), out)
        self.assertEqual(urls, [self.URL])
        self.assertEqual(snapshot(out), files)

    def test_bad_bundle_touches_nothing(self):
        home = self.wine("rosetta")
        before = snapshot(home)
        data = tarball(bundle_files())
        checkout = self.checkout(data, sha256="0" * 64)
        fetch, _ = self.fake(data)
        with self.assertRaises(DaocError) as cm:
            mtld3d.fetch_bundle(checkout, fetch_url=fetch)
        self.assertIn("sha256", cm.exception.msg.lower())
        self.assertFalse((checkout.downloads / f"mtld3d-{VERSION}").exists())
        self.assertFalse((checkout.downloads / "mtld3d.tar.xz").exists())
        self.assertEqual(snapshot(home), before)

    def test_fetch_refuses_unsafe_members(self):
        for name in ("../escape", "/abs/path"):
            with self.subTest(name=name):
                data = tarball({name: b"x"})
                checkout = self.checkout(data)
                fetch, _ = self.fake(data)
                with self.assertRaises(DaocError):
                    mtld3d.fetch_bundle(checkout, fetch_url=fetch)
                self.assertFalse((checkout.downloads / f"mtld3d-{VERSION}").exists())
                self.assertFalse((self.root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
