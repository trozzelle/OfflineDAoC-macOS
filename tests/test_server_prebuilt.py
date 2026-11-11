"""The prebuilt server: pack, install, and the refusals that keep a save safe."""
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import pins, release, server
from daoc_cli.checkout import Checkout
from daoc_cli.files import sha256


class PrebuiltTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = make_checkout(self.tmp)
        self.co = Checkout(self.root)
        self.pin = pins.shipped(self.co, "server", "0.35")
        self.ref = self.pin["ref"]
        self.stubs = path_stubs(self.tmp, {"git": "exit 1", "cmake": "exit 1"})

    # A Server install as a build leaves it, packed by server.pack.
    def built_tarball(self, ref=None):
        build = Checkout(self.root, home=self.tmp / "builder")
        sd = build.server_dir
        (sd / "bin").mkdir(parents=True)
        (sd / "bin" / "CoreServer").write_text("#!/bin/sh\n")
        os.symlink("../config", sd / "bin" / "config")
        (sd / "defaults").mkdir()
        (sd / "defaults" / "world.sqlite").write_bytes(b"world")
        (sd / "navmesh").mkdir()
        (sd / "navmesh" / "zone000.nav").write_bytes(b"nav")
        (sd / "daoc-server.sh").write_text("#!/bin/sh\necho stopped\n")
        (sd / "daoc-server.sh").chmod(0o755)
        for name in server.USER_DIRS:
            (sd / name).mkdir()
            (sd / name / "builder.txt").write_text("the builder's own")
        pins.record_installed(build, "server", dict(self.pin, ref=ref or self.ref))
        return server.pack(build, "0.35", ref or self.ref, self.tmp / "out")

    def ship(self, tarball, sha=None):
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["versions"]["0.35"]["server"]["prebuilt"] = {
            "url": f"https://example.invalid/{tarball.name}",
            "bytes": tarball.stat().st_size, "sha256": sha or sha256(tarball)}
        path.write_text(json.dumps(manifest))

    def existing_install(self):
        sd = self.co.server_dir
        (sd / "bin").mkdir(parents=True)
        (sd / "bin" / "old.dll").write_text("old")
        (sd / "config").mkdir()
        (sd / "config" / "serverconfig.xml").write_text("mine")
        (sd / "data").mkdir()
        (sd / "data" / "opendaoc.sqlite3.db").write_text("my save")

    def install(self, tarball, *argv):
        def fetch(url, dest):
            shutil.copyfile(tarball, dest)
        with mock.patch.object(release, "download", fetch):
            return run_cli(["server", "install", *argv], self.root,
                           env={"PATH": f"{self.stubs}:/usr/bin:/bin"})

    def test_pack_leaves_user_folders_out_and_keeps_links(self):
        tarball = self.built_tarball()
        self.assertEqual(tarball.name, f"daoc-server-0.35-{self.ref[:12]}-osx-arm64.tar.xz")
        with tarfile.open(tarball) as archive:
            members = {m.name: m for m in archive.getmembers()}
        self.assertTrue(members["daoc-server/bin/config"].issym())
        self.assertEqual(members["daoc-server/bin/config"].linkname, "../config")
        self.assertIn("daoc-server/navmesh/zone000.nav", members)
        self.assertIn("daoc-server/.daoc-pin.json", members)
        self.assertEqual([n for n in members if n.split("/")[1:2] and n.split("/")[1] in server.USER_DIRS], [])

    def test_pack_refuses_an_install_built_from_another_commit(self):
        self.built_tarball()
        build = Checkout(self.root, home=self.tmp / "builder")
        with self.assertRaises(server.DaocError):
            server.pack(build, "0.35", "f" * 40, self.tmp / "out")

    def test_installs_the_prebuilt_server_and_keeps_the_save(self):
        tarball = self.built_tarball()
        self.ship(tarball)
        self.existing_install()
        code, _, err = self.install(tarball)
        self.assertEqual(code, 0, err)
        sd = self.co.server_dir
        self.assertTrue((sd / "bin" / "CoreServer").is_file())
        self.assertFalse((sd / "bin" / "old.dll").exists())
        self.assertEqual(os.readlink(sd / "bin" / "config"), "../config")
        self.assertEqual((sd / "config" / "serverconfig.xml").read_text(), "mine")
        self.assertEqual((sd / "data" / "opendaoc.sqlite3.db").read_text(), "my save")
        self.assertEqual((sd / "config" / "edition").read_text(), "sluaghbinder\n")
        record = pins.installed(self.co, "server")
        self.assertEqual(record["ref"], self.ref)
        self.assertNotIn("prebuilt", record)
        self.assertEqual(stub_calls(self.stubs), [])

    def test_a_checksum_mismatch_changes_nothing(self):
        tarball = self.built_tarball()
        self.ship(tarball, sha="0" * 64)
        self.existing_install()
        code, _, err = self.install(tarball)
        self.assertEqual(code, 1)
        self.assertIn("failed SHA-256 verification", err)
        self.assertTrue((self.co.server_dir / "bin" / "old.dll").exists())

    def test_a_tarball_built_from_another_commit_is_refused(self):
        tarball = self.built_tarball(ref="f" * 40)
        self.ship(tarball)
        self.existing_install()
        code, _, err = self.install(tarball)
        self.assertEqual(code, 1)
        self.assertIn("built from ffffffffffff", err)
        self.assertTrue((self.co.server_dir / "bin" / "old.dll").exists())

    def adversarial(self, name, data=b"x", link=None):
        tarball = self.tmp / f"bad-{len(list(self.tmp.glob('bad-*.tar.xz')))}.tar.xz"
        with tarfile.open(tarball, "w:xz") as archive:
            info = tarfile.TarInfo(name)
            if link is None:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                info.type, info.linkname = tarfile.SYMTYPE, link
                archive.addfile(info)
        return tarball

    def test_user_folders_escaping_paths_and_outside_links_are_refused(self):
        self.existing_install()
        for tarball, words in ((self.adversarial("daoc-server/data/opendaoc.sqlite3.db"), "holds data/"),
                               (self.adversarial("daoc-server/../evil"), "unexpected member"),
                               (self.adversarial("elsewhere/x"), "unexpected member"),
                               (self.adversarial("daoc-server/Data/x"), "holds Data/"),
                               (self.adversarial("daoc-server/bin/x", link="../../../etc"), "points outside")):
            self.ship(tarball)
            code, _, err = self.install(tarball)
            self.assertEqual(code, 1, err)
            self.assertIn(words, err)
            self.assertEqual((self.co.server_dir / "data" / "opendaoc.sqlite3.db").read_text(), "my save")

    def test_an_interrupted_swap_leaves_no_record_of_the_pinned_commit(self):
        tarball = self.built_tarball()
        self.ship(tarball)
        self.existing_install()
        real, calls = Path.rename, []

        def failing(path, target):
            calls.append(path.name)
            if len(calls) == 2:
                raise OSError("disk went away")
            return real(path, target)

        with mock.patch.object(Path, "rename", failing):
            with self.assertRaises(OSError):
                self.install(tarball)
        self.assertTrue((self.co.server_dir / "bin" / "CoreServer").is_file())   # swap began
        self.assertIsNone(pins.installed(self.co, "server"))
        self.assertFalse((self.co.server_dir / pins.INSTALLED).exists())


if __name__ == "__main__":
    unittest.main()
