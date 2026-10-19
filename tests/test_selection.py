"""The Selection: the Game and Default client a Checkout is set up for."""
import json
import tempfile
import unittest

from tests.support import make_checkout

from daoc_cli import pins, selection
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.games import Game
from daoc_cli.selection import Selection


class SelectionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(tmp.name)
        self.co = Checkout(self.root)
        self.file = self.root / ".daoc" / selection.FILE
        # The real sha256 of these stand-in files is replaced by the hashes they stand for.
        self.hashes = {}
        original = selection.sha256
        selection.sha256 = lambda path: self.hashes.get(path.name) or original(path)
        self.addCleanup(setattr, selection, "sha256", original)

    def original_install(self, record=None, **dlls):
        self.co.app_dir.mkdir(parents=True)
        for name, sha in dlls.items():
            name = name.replace("_orig", ".orig").replace("game_dll", "game.dll")
            (self.co.app_dir / name).write_bytes(b"x")
            self.hashes[name] = sha
        if record is not None:
            pins.record_installed(self.co, "original_client", record)

    def test_no_file_no_install_is_default(self):
        self.assertEqual(selection.load(self.co), Selection(Game("0.35", "sluaghbinder"), "original"))
        self.assertFalse(self.file.exists())

    def test_file_wins(self):
        self.original_install({"version": "0.35b", "edition": "sluaghbinder"})
        self.file.parent.mkdir(exist_ok=True)
        self.file.write_text(json.dumps({"game": "0.36", "client": "new", "switching_to": None}))
        self.assertEqual(selection.load(self.co), Selection(Game("0.36", "classic"), "new"))

    def test_round_trip_with_switching_to(self):
        sel = Selection(Game("0.35", "sluaghbinder"), "original", Game("0.36", "sluaghbinder"), "new")
        selection.save(self.co, sel)
        self.assertEqual(json.loads(self.file.read_text()),
                         {"game": "0.35b", "client": "original", "switching_to": "0.36b",
                          "switching_client": "new"})
        self.assertEqual(selection.load(self.co), sel)

    def test_infer_from_record(self):
        self.original_install({"version": "0.36b", "edition": "classic"})
        self.assertEqual(selection.infer(self.co), Selection(Game("0.36", "classic"), "original"))

    def test_a_release_two_versions_share_is_the_preferred_versions(self):
        # 0.37's original client is the v0.36b release: an install of it serves both Versions.
        self.original_install({"version": "0.36b", "edition": "sluaghbinder"})
        self.assertEqual(selection.original_game(self.co, prefer="0.37"), Game("0.37", "sluaghbinder"))
        self.assertEqual(selection.original_game(self.co, prefer="0.36"), Game("0.36", "sluaghbinder"))
        self.assertEqual(selection.original_game(self.co, prefer="0.35"), Game("0.36", "sluaghbinder"))
        self.assertEqual(selection.infer(self.co).game, Game("0.36", "sluaghbinder"))

    def test_infer_legacy_record_without_edition(self):
        self.original_install({"version": "0.35b"}, game_dll="ff" * 32,
                              game_dll_orig=pins.LEGACY_CLIENT["game_dll_sha256"])
        self.assertEqual(selection.infer(self.co).game, Game("0.35", "sluaghbinder"))
        self.hashes["game.dll.orig"] = "f55ed6b068e22ce8e1106871c2fad6ee10c18390bbb8b5dc772219ad8c8b83bb"
        self.assertEqual(selection.infer(self.co).game, Game("0.35", "classic"))

    def test_infer_record_less_legacy_install(self):
        self.original_install(game_dll=pins.LEGACY_CLIENT["game_dll_sha256"])
        self.assertEqual(selection.infer(self.co), Selection(Game("0.35", "sluaghbinder"), "original"))

    def test_infer_new_client_only(self):
        self.co.new_client_root.mkdir(parents=True)
        pins.record_installed(self.co, "new_client", {"version": "0.36c", "game": "0.36b"})
        self.assertEqual(selection.infer(self.co), Selection(Game("0.36", "sluaghbinder"), "new"))

    def test_infer_nothing_known(self):
        self.original_install({"version": "0.31"})
        self.assertIsNone(selection.infer(self.co))
        self.assertEqual(selection.load(self.co).game, Game("0.35", "sluaghbinder"))

    def test_corrupt_file_is_error_naming_path(self):
        self.file.parent.mkdir()
        self.file.write_text("{not json")
        with self.assertRaises(DaocError) as cm:
            selection.load(self.co)
        self.assertIn(str(self.file), cm.exception.msg)

    def test_unknown_game_in_file_is_error(self):
        self.file.parent.mkdir()
        for content in ({"game": "0.31b", "client": "original"}, {"game": "0.36", "client": "both"}):
            with self.subTest(content=content):
                self.file.write_text(json.dumps(content))
                with self.assertRaises(DaocError) as cm:
                    selection.load(self.co)
                self.assertIn(str(self.file), cm.exception.msg)


if __name__ == "__main__":
    unittest.main()
