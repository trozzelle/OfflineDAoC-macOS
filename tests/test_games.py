"""The Game catalogue: parsing Game names and reading the schema 2 manifest."""
import tempfile
import unittest

from tests.support import make_checkout

from daoc_cli import games
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.games import Game

SLUAGHBINDER_DLL = "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b"
CLASSIC_DLL = "f55ed6b068e22ce8e1106871c2fad6ee10c18390bbb8b5dc772219ad8c8b83bb"


class ParseTest(unittest.TestCase):
    def test_parse_b_is_sluaghbinder(self):
        game = games.parse("0.36b")
        self.assertEqual(game, Game("0.36", "sluaghbinder"))
        self.assertEqual(game.name, "0.36b")

    def test_parse_plain_is_classic(self):
        game = games.parse("0.35")
        self.assertEqual(game, Game("0.35", "classic"))
        self.assertEqual(game.name, "0.35")

    def test_parse_rejects(self):
        for name in ("0.36c", "v0.36", "", "0.36bb", "0.36.1", "b"):
            with self.subTest(name=name):
                with self.assertRaises(DaocError) as cm:
                    games.parse(name)
                self.assertEqual(cm.exception.code, 2)


class CatalogueTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.co = Checkout(make_checkout(tmp.name))

    def test_versions_sorted(self):
        self.assertEqual(games.versions(self.co), ["0.35", "0.36", "0.37"])

    def test_unknown_version_names_known(self):
        with self.assertRaises(DaocError) as cm:
            games.entry(self.co, "0.99")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("0.99", cm.exception.msg)
        self.assertIn("0.35, 0.36, 0.37", cm.exception.msg)

    def test_check_refuses_unknown_game(self):
        with self.assertRaises(DaocError):
            games.check(self.co, Game("0.34", "classic"))
        games.check(self.co, Game("0.36", "sluaghbinder"))

    def test_new_client_only_from_036(self):
        self.assertFalse(games.new_client_supported(self.co, "0.35"))
        self.assertTrue(games.new_client_supported(self.co, "0.36"))

    def test_default_is_035b_original(self):
        self.assertEqual(games.default(self.co), (Game("0.35", "sluaghbinder"), "original"))

    def test_edition_sha(self):
        self.assertEqual(games.edition_sha(self.co, Game("0.36", "sluaghbinder")), SLUAGHBINDER_DLL)
        self.assertEqual(games.edition_sha(self.co, Game("0.36", "classic")), CLASSIC_DLL)


if __name__ == "__main__":
    unittest.main()
