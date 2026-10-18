"""daoc game switch: the order of its steps, its refusals (before anything is touched), and resuming."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import (client, client_runtime, game, games, newclient, pins, release, saves, selection,
                      server)
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.games import Game
from daoc_cli.selection import Selection

G = games.parse


class SwitchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(tmp.name)
        self.co = Checkout(self.root)
        self.calls = []
        self.server_built = False
        self.save = {"exists": True, "edition": "sluaghbinder", "game": None,
                     "counts": {"sluaghbinder_characters": 0, "sluaghbinder_bots": 0}}
        self.running = None
        self.port = 10300
        self.fail_upgrade = 0
        self.selections = []
        self.select(G("0.35b"), "original")

        def rec(name, result=None):
            def fn(*args, **kwargs):
                self.calls.append(name)
                return result
            return fn

        def install_server(checkout, version, verbose=False, pin=None):
            self.calls.append(f"server.install {version}")
            self.server_built = True

        def built_from(checkout, group, pin):
            if group == "server":
                return "x", self.server_built
            return pins.NOT_INSTALLED, None

        def upgrade(checkout, previous, edition, leave_bots):
            if self.fail_upgrade:
                self.fail_upgrade -= 1
                raise DaocError("daoc-progress upgrade failed")
            self.calls.append(f"upgrade {edition}{' leave' if leave_bots else ''}")
            return self.root

        def save_selection(checkout, sel):
            self.selections.append(sel)
            self.calls.append("pending" if sel.switching_to else "selection")
            real_save(checkout, sel)

        def client_install(checkout, flavour=None, verbose=False, game=None, download_only=False):
            self.calls.append(f"{'download' if download_only else 'install'} original {game.name}")

        def new_install(checkout, game, fetch_url=None, download_only=False):
            self.calls.append(f"{'stage' if download_only else 'install'} new {game.name}")

        def stop(checkout):
            self.calls.append("stop client")
            self.running = None

        real_save = selection.save
        patches = [
            mock.patch.object(saves, "exists", lambda c: self.save["exists"]),
            mock.patch.object(saves, "edition", lambda c: self.save["edition"] if self.save["exists"] else None),
            mock.patch.object(saves, "save_game", lambda c, default: self.save["game"] or default),
            mock.patch.object(saves, "mark", lambda c, g: self.save.update(game=g)),
            mock.patch.object(saves, "inspect", lambda c: self.calls.append("inspect") or self.save["counts"]),
            mock.patch.object(saves, "upgrade", upgrade),
            mock.patch.object(saves, "restore", rec("restore")),
            mock.patch.object(saves, "fresh", rec("fresh")),
            mock.patch.object(saves, "backups", lambda c: [(self.root / "b1", {"game": "0.35b"})]),
            mock.patch.object(server, "install", install_server),
            mock.patch.object(server, "_stop_first", rec("stop server")),
            mock.patch.object(server, "set_edition", lambda c, e: self.calls.append(f"set_edition {e}")),
            mock.patch.object(pins, "built_from", built_from),
            mock.patch.object(client, "install", client_install),
            mock.patch.object(newclient, "install", new_install),
            mock.patch.object(client_runtime, "running_client", lambda c: self.running),
            mock.patch.object(client_runtime, "stop", stop),
            mock.patch.object(client_runtime, "default_port", lambda c: self.port),
            mock.patch.object(selection, "save", save_selection),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def select(self, g, client_name):
        selection.save(self.co, Selection(g, client_name))

    def switch(self, name, client_name=None, leave=False, restore=None, fresh=False):
        self.calls.clear()
        with redirect_stderr(io.StringIO()) as err:
            game.switch(self.co, G(name), client_name, leave, restore, fresh)
        return err.getvalue()

    def installed(self, *which):
        if "original" in which:
            self.co.client_root.mkdir(parents=True, exist_ok=True)
        if "new" in which:
            self.co.new_client_root.mkdir(parents=True, exist_ok=True)

    def test_order(self):
        self.installed("original")
        self.running = "original"
        self.switch("0.36")
        self.assertEqual(self.calls, [
            "inspect", "pending", "download original 0.36", "stop client", "stop server",
            "server.install 0.36", "set_edition classic", "upgrade classic", "install original 0.36",
            "selection"])
        self.assertEqual(selection.load(self.co), Selection(G("0.36"), "original"))
        self.assertEqual(self.save["game"], G("0.36"))

    def test_new_client_is_staged_before_anything_stops(self):
        self.installed("original", "new")
        self.switch("0.36b", "new")
        self.assertLess(self.calls.index("stage new 0.36b"), self.calls.index("stop server"))
        self.assertIn("install new 0.36b", self.calls)
        self.assertEqual(selection.load(self.co).client, "new")

    def test_preflight_refusals_touch_nothing(self):
        cases = {
            "--client new on 0.35": dict(name="0.35b", client_name="new"),
            "port with new": dict(name="0.36b", client_name="new", port=20300),
            "older version": dict(name="0.35b", current=G("0.36b")),
            "restore and fresh": dict(name="0.36b", restore="b1", fresh=True),
            "sluaghbinder characters": dict(name="0.36", chars=2),
            "sluaghbinder bots": dict(name="0.36", bots=1),
        }
        for label, case in cases.items():
            with self.subTest(label):
                self.port = case.get("port", 10300)
                self.save["counts"] = {"sluaghbinder_characters": case.get("chars", 0),
                                       "sluaghbinder_bots": case.get("bots", 0)}
                self.select(case.get("current", G("0.35b")), "original")
                self.calls.clear()
                with self.assertRaises(DaocError) as cm, redirect_stderr(io.StringIO()):
                    game.switch(self.co, G(case["name"]), case.get("client_name"), False,
                                case.get("restore"), case.get("fresh", False))
                self.assertEqual(cm.exception.code, 2, cm.exception.msg)
                self.assertEqual([c for c in self.calls if c != "inspect"], [], label)
                if label == "sluaghbinder bots":
                    self.assertIn("--leave-sluaghbinder-bots", cm.exception.msg)
                if label == "port with new":
                    self.assertIn("10300", cm.exception.msg)

    def test_unknown_game_is_refused(self):
        with self.assertRaises(DaocError) as cm:
            game.switch(self.co, G("0.37"), None, False, None, False)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(self.calls, [])

    def test_bots_left_behind_when_asked(self):
        self.save["counts"] = {"sluaghbinder_characters": 0, "sluaghbinder_bots": 3}
        self.switch("0.36", leave=True)
        self.assertIn("upgrade classic leave", self.calls)

    def test_edition_only_switch_skips_server_build(self):
        self.server_built = True
        self.switch("0.35")
        self.assertNotIn("server.install 0.35", self.calls)
        self.assertIn("set_edition classic", self.calls)
        self.assertIn("upgrade classic", self.calls)

    def test_same_game_is_noop_except_missing_steps(self):
        self.server_built = True
        self.save["edition"] = "classic"
        self.switch("0.35b")
        self.assertEqual(self.calls, ["pending", "stop server", "set_edition sluaghbinder",
                                      "upgrade sluaghbinder", "selection"])

    def test_nothing_to_do(self):
        self.server_built = True
        err = self.switch("0.35b")
        self.assertEqual(self.calls, ["pending", "stop server", "set_edition sluaghbinder", "selection"])
        self.assertIn("0.35b", err)

    def test_pending_written_before_and_cleared_after(self):
        self.switch("0.36b")
        self.assertEqual(self.selections[0].switching_to, G("0.36b"))
        self.assertEqual(self.selections[0].game, G("0.35b"))
        self.assertIsNone(self.selections[-1].switching_to)

    def test_rerun_after_interrupt_resumes(self):
        self.fail_upgrade = 1
        with self.assertRaises(DaocError):
            self.switch("0.36b")
        self.assertIn("server.install 0.36", self.calls)
        self.assertEqual(selection.load(self.co).switching_to, G("0.36b"))
        self.switch("0.36b")
        self.assertNotIn("server.install 0.36", self.calls)
        self.assertIn("upgrade sluaghbinder", self.calls)
        self.assertIsNone(selection.load(self.co).switching_to)

    def test_new_default_falls_back_on_035(self):
        self.installed("new")
        self.select(G("0.36b"), "new")
        err = self.switch("0.35b", restore="b1")
        self.assertEqual(selection.load(self.co).client, "original")
        self.assertIn("the new client exists from 0.36", err)
        self.assertTrue(self.co.new_client_root.is_dir())
        self.assertFalse([c for c in self.calls if c.endswith("new 0.35b")])
        self.assertIn("install original 0.35b", self.calls)

    def test_older_version_with_restore(self):
        self.select(G("0.36b"), "original")
        self.switch("0.35b", restore="b1")
        self.assertIn("restore", self.calls)
        self.assertLess(self.calls.index("server.install 0.35"), self.calls.index("restore"))
        self.assertEqual(selection.load(self.co).game, G("0.35b"))

    def test_older_version_with_fresh_save(self):
        self.select(G("0.36b"), "original")
        self.switch("0.35", fresh=True)
        self.assertIn("fresh", self.calls)
        self.assertFalse([c for c in self.calls if c.startswith("upgrade")])

    def test_cli_switch_and_list(self):
        self.server_built = True
        code, out, err = run_cli(["game", "switch", "0.35b"], self.root)
        self.assertEqual(code, 0, err)
        code, out, err = run_cli(["game"], self.root)
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"0\.35b\s+Sluaghbinder\s+original\s+\* selected")
        self.assertRegex(out, r"0\.36\s+Classic classes\s+original, new")
        code, _, err = run_cli(["game", "switch", "0.36b", "--restore", "x", "--fresh-save"], self.root)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
