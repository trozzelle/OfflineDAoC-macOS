"""The save across a switch: its Edition, upgrades with metadata, restore and fresh saves."""
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr

from tests.support import make_checkout

from daoc_cli import saves
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.games import Game

PROGRESS = """#!/bin/sh
echo "$@" >> "$(dirname "$0")/progress.calls"
case "$1" in
  inspect) echo '{"accounts":1,"characters":2,"bots":3,"inventory":4,"sluaghbinder_characters":1,"sluaghbinder_bots":0}' ;;
  upgrade)
    b="$(dirname "$0")/data/progress-backups/20261017-120000-abcdef"
    mkdir -p "$b" && cp "$(dirname "$0")/data/opendaoc.sqlite3.db" "$b/"
    echo "Done. Report: $b/import-report.txt" ;;
esac
"""


class SavesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.co = Checkout(make_checkout(tmp.name))
        self.data = self.co.server_dir / "data"
        self.data.mkdir(parents=True)
        tool = self.co.server_dir / "daoc-progress"
        tool.write_text(PROGRESS)
        tool.chmod(0o755)

    def make_save(self, value="False"):
        con = sqlite3.connect(str(self.data / saves.SAVE_FILE))
        con.execute('CREATE TABLE ServerProperty ("Key" TEXT, Value TEXT)')
        con.execute("INSERT INTO ServerProperty VALUES ('enable_sluaghbinder', ?)", (value,))
        con.commit()
        con.close()

    def quiet(self, fn, *args):
        with redirect_stderr(io.StringIO()):
            return fn(*args)

    def test_edition_reads_property(self):
        self.assertIsNone(saves.edition(self.co))
        self.make_save("False")
        self.assertEqual(saves.edition(self.co), "classic")
        (self.data / saves.SAVE_FILE).unlink()
        self.make_save("True")
        self.assertEqual(saves.edition(self.co), "sluaghbinder")

    def test_edition_reads_a_wal_save_without_its_sidecars(self):
        # A restored backup is a WAL-mode database copied in without -wal/-shm,
        # which a plain read-only open cannot start (it may not create them).
        con = sqlite3.connect(str(self.data / saves.SAVE_FILE))
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        self.make_save("False")
        for suffix in ("-wal", "-shm"):
            (self.data / (saves.SAVE_FILE + suffix)).unlink(missing_ok=True)
        self.assertEqual(saves.edition(self.co), "classic")

    def test_inspect_parses_json(self):
        self.make_save()
        self.assertEqual(saves.inspect(self.co)["sluaghbinder_characters"], 1)

    def test_upgrade_writes_metadata(self):
        self.make_save()
        folder = self.quiet(saves.upgrade, self.co, Game("0.35", "sluaghbinder"), "classic", True)
        self.assertEqual(folder.name, "20261017-120000-abcdef")
        meta = json.loads((folder / saves.META).read_text())
        self.assertEqual(meta["game"], "0.35b")
        calls = (self.co.server_dir / "progress.calls").read_text().split()
        self.assertEqual(calls, ["upgrade", "--edition=classic", "--leave-sluaghbinder-bots"])
        self.assertEqual(saves.backups(self.co)[0][0], folder)

    def test_restore_checks_version(self):
        self.make_save()
        folder = self.quiet(saves.upgrade, self.co, Game("0.35", "sluaghbinder"), "classic", False)
        with self.assertRaises(DaocError) as cm:
            saves.restore(self.co, folder.name, "0.36")
        self.assertEqual(cm.exception.code, 2)
        (self.data / saves.SAVE_FILE).write_bytes(b"current")
        self.quiet(saves.restore, self.co, folder.name, "0.35", Game("0.36", "classic"))
        self.assertNotEqual((self.data / saves.SAVE_FILE).read_bytes(), b"current")
        kept = [f for f, meta in saves.backups(self.co) if meta["game"] == "0.36"]
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0] / saves.SAVE_FILE).read_bytes(), b"current")
        self.assertEqual(saves.save_game(self.co, Game("0.36", "classic")), Game("0.35", "sluaghbinder"))

    def test_unknown_backup_is_refused(self):
        with self.assertRaises(DaocError) as cm:
            saves.restore(self.co, "nope", "0.35")
        self.assertIn("nope", cm.exception.msg)

    def test_fresh_moves_save(self):
        self.make_save()
        (self.data / (saves.SAVE_FILE + "-wal")).write_bytes(b"wal")
        folder = self.quiet(saves.fresh, self.co, Game("0.36", "sluaghbinder"))
        self.assertFalse(saves.exists(self.co))
        self.assertFalse((self.data / (saves.SAVE_FILE + "-wal")).exists())
        self.assertTrue((folder / saves.SAVE_FILE).is_file())
        self.assertEqual(json.loads((folder / saves.META).read_text())["game"], "0.36b")

    def test_restore_keeps_rows_that_only_the_wal_holds(self):
        # A save set aside after an unclean stop keeps committed rows in its -wal.
        work = self.data / "work"
        work.mkdir()
        con = sqlite3.connect(str(work / saves.SAVE_FILE))
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute('CREATE TABLE ServerProperty ("Key" TEXT, Value TEXT)')
        con.execute("INSERT INTO ServerProperty VALUES ('enable_sluaghbinder', 'False')")
        con.commit()
        folder = saves._backups_dir(self.co) / "20261018-000000-fresh"
        folder.mkdir(parents=True)
        for suffix in ("", "-wal"):
            shutil.copyfile(work / (saves.SAVE_FILE + suffix), folder / (saves.SAVE_FILE + suffix))
        con.close()
        (folder / saves.META).write_text(json.dumps({"game": "0.35b"}))
        self.quiet(saves.restore, self.co, folder.name, "0.35")
        self.assertEqual(saves.edition(self.co), "classic")

    def test_save_game_marker(self):
        self.make_save()
        self.assertEqual(saves.save_game(self.co, Game("0.35", "sluaghbinder")), Game("0.35", "sluaghbinder"))
        saves.mark(self.co, Game("0.36", "classic"))
        self.assertEqual(saves.save_game(self.co, Game("0.35", "sluaghbinder")), Game("0.36", "classic"))


if __name__ == "__main__":
    unittest.main()
