"""The Original client's Edition: which game.dll the install holds, swapped without a re-extract."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from tests.support import make_checkout
from tests.test_client_install import FakeDownloads, make_release
from tests.test_client_patch import SPEC, pristine_bytes, sha

from daoc_cli import client, client_patch, client_runtime, pins, release
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.games import Game

ROOT = "OfflineDAoC-vT"
DLL = "runtime/client-opendaoc/app/game.dll"
MEMBER = f"{ROOT}/editions/0.36-no-custom-class/{DLL}"
SLUAGH = pristine_bytes()
CLASSIC = SLUAGH[:0x20] + b"\xdd" * 16 + SLUAGH[0x30:]  # same patch sites, another build


class EditionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(tmp.name)
        pin, self.served = make_release({f"{ROOT}/{DLL}": SLUAGH, MEMBER: CLASSIC,
                                         f"{ROOT}/readme.txt": b"release T"})
        self.pin = dict(pin, editions={
            "sluaghbinder": {"game_dll_sha256": sha(SLUAGH)},
            "classic": {"game_dll_sha256": sha(CLASSIC), "game_dll_member": MEMBER},
        })
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["versions"]["0.36"]["original_client"] = self.pin
        path.write_text(json.dumps(manifest))
        self.co = Checkout(self.root)
        proven = mock.patch.dict(client_patch.PROVEN_BUILDS, {sha(SLUAGH): SPEC, sha(CLASSIC): SPEC})
        proven.start()
        self.addCleanup(proven.stop)
        running = mock.patch.object(client_runtime, "game_pids", return_value=[])
        self.game_pids = running.start()
        self.addCleanup(running.stop)
        self.downloads = FakeDownloads(self.served)

    def install(self, game):
        with redirect_stderr(io.StringIO()):
            client.install_release(self.co, game, self.downloads)

    def apply(self, game):
        with redirect_stderr(io.StringIO()):
            return client.apply_edition(self.co, game, self.downloads)

    def pristine(self):
        return (self.co.app_dir / "game.dll.orig").read_bytes()

    def test_install_on_version_change_reextracts_then_applies_edition(self):
        self.install(Game("0.36", "classic"))
        self.assertEqual((self.co.client_root / "readme.txt").read_bytes(), b"release T")
        self.assertEqual(self.pristine(), CLASSIC)
        record = pins.installed(self.co, "original_client")
        self.assertEqual((record["version"], record["edition"], record["game_dll_sha256"]),
                         ("T", "classic", sha(CLASSIC)))

    def test_classic_swaps_from_editions_folder(self):
        self.install(Game("0.36", "sluaghbinder"))
        self.assertEqual(pins.installed(self.co, "original_client")["edition"], "sluaghbinder")
        self.downloads.urls.clear()
        self.assertTrue(self.apply(Game("0.36", "classic")))
        self.assertEqual(self.pristine(), CLASSIC)
        self.assertNotEqual((self.co.app_dir / "game.dll").read_bytes(), CLASSIC)  # patched
        self.assertEqual(pins.installed(self.co, "original_client")["edition"], "classic")
        self.assertEqual(self.downloads.urls, [])  # read from the install's editions folder

    def test_back_to_sluaghbinder_reads_archive_member(self):
        self.install(Game("0.36", "classic"))
        self.assertTrue(self.apply(Game("0.36", "sluaghbinder")))
        self.assertEqual(self.pristine(), SLUAGH)
        self.assertEqual(pins.installed(self.co, "original_client")["game_dll_sha256"], sha(SLUAGH))

    def test_same_edition_is_noop(self):
        self.install(Game("0.36", "sluaghbinder"))
        dll = self.co.app_dir / "game.dll"
        before = dll.stat().st_mtime_ns
        self.assertFalse(self.apply(Game("0.36", "sluaghbinder")))
        self.assertEqual(dll.stat().st_mtime_ns, before)

    def test_wrong_member_hash_refused(self):
        self.install(Game("0.36", "sluaghbinder"))
        (self.co.client_root / MEMBER[len(ROOT) + 1:]).write_bytes(b"tampered")
        before = (self.co.app_dir / "game.dll").read_bytes()
        with self.assertRaises(DaocError) as cm:
            self.apply(Game("0.36", "classic"))
        self.assertIn("classic game.dll", cm.exception.msg)
        self.assertEqual((self.co.app_dir / "game.dll").read_bytes(), before)
        self.assertEqual(self.pristine(), SLUAGH)

    def test_refuses_while_running(self):
        self.install(Game("0.36", "sluaghbinder"))
        self.game_pids.return_value = [42]
        with self.assertRaises(DaocError) as cm:
            self.apply(Game("0.36", "classic"))
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.pristine(), SLUAGH)

    def test_edition_change_does_not_reextract(self):
        self.install(Game("0.36", "sluaghbinder"))
        with mock.patch.object(release, "extract") as extract:
            self.install(Game("0.36", "classic"))
        extract.assert_not_called()
        self.assertEqual(self.pristine(), CLASSIC)

    def test_unknown_dll_is_left_for_the_patch_to_refuse(self):
        # Neither Edition's build: no swap and no download; the Client patch then refuses it.
        self.install(Game("0.36", "sluaghbinder"))
        (self.co.app_dir / "game.dll.orig").write_bytes(b"unknown build")
        self.downloads.urls.clear()
        self.assertFalse(self.apply(Game("0.36", "classic")))
        self.assertEqual(self.pristine(), b"unknown build")
        self.assertEqual(self.downloads.urls, [])


if __name__ == "__main__":
    unittest.main()
