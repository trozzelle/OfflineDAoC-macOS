"""The New client install: Godot, then the release's parts streamed into a staged godot/ tree."""
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support import make_checkout, run_cli
from tests.test_client_patch import sha

from daoc_cli import games, newclient, pins, selection
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.games import Game
from daoc_cli.selection import Selection

URL = "https://example.invalid/0.36c/"
GODOT_URL = "https://example.invalid/godot.zip"
ROOT = "OfflineDAoC-v0.36c"
STAMP = (2026, 10, 9, 12, 30, 0)
GAME = Game("0.36", "sluaghbinder")


def zip_bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=STAMP)
            zf.writestr(info, data)
    return buf.getvalue()


def part_entries(n):
    return {
        f"{ROOT}/new-client/godot/content/zone{n}.png": f"zone {n}".encode(),
        f"{ROOT}/new-client/tools/godot_net/Godot_{n}.exe": b"windows",
        f"{ROOT}/new-client/runtime/a{n}.dll": b"launcher",
        f"{ROOT}/START OFFLINE DAOC - NEW CLIENT.cmd": b"cmd",
    }


class Served:
    def __init__(self, served):
        self.served = served
        self.urls = []
        self.fail = set()

    def __call__(self, url, dest):
        self.urls.append(url)
        if url in self.fail:
            raise DaocError(f"download of {url} failed")
        dest.write_bytes(self.served[url])


class NewClientInstallTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(tmp.name)
        parts = {f"OfflineDAoC-v0.36c-part0{n}.zip": zip_bytes(part_entries(n)) for n in (1, 2, 3)}
        parts["OfflineDAoC-v0.36c-part01.zip"] = zip_bytes(dict(part_entries(1), **{
            f"{ROOT}/new-client/godot/project.godot": b"[application]\n"}))
        godot = zip_bytes({"Godot_mono.app/Contents/MacOS/Godot": b"#!/bin/sh\n",
                           "Godot_mono.app/Contents/Info.plist": b"<plist/>"})
        self.served = {URL + name: data for name, data in parts.items()}
        self.served[GODOT_URL] = godot
        self.pin = {
            "release_url": URL, "version": "0.36c", "manifest_asset": "download-manifest.json",
            "root_folder": ROOT, "unpacked_bytes": 1000,
            "parts": [{"name": n, "bytes": len(d), "sha256": sha(d)} for n, d in parts.items()],
            "godot": {"url": GODOT_URL, "bytes": len(godot), "sha256": sha(godot)},
        }
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["versions"]["0.36"]["new_client"] = self.pin
        path.write_text(json.dumps(manifest))
        self.co = Checkout(self.root)
        self.fetch = Served(self.served)
        dotnet = mock.patch.object(newclient, "ensure_dotnet")
        dotnet.start()
        self.addCleanup(dotnet.stop)

    def install(self, game=GAME, **kwargs):
        with redirect_stderr(io.StringIO()) as err:
            newclient.install(self.co, game, self.fetch, **kwargs)
        return err.getvalue()

    def files(self):
        project = self.co.new_client_project
        return sorted(str(p.relative_to(project)) for p in project.rglob("*") if p.is_file())

    def test_keeps_only_godot_tree(self):
        self.install()
        self.assertEqual(self.files(), ["content/zone1.png", "content/zone2.png", "content/zone3.png",
                                        "project.godot"])
        self.assertEqual(sorted(p.name for p in self.co.new_client_root.iterdir()),
                         [pins.INSTALLED, "godot"])
        self.assertTrue((self.co.godot_app / "Contents" / "MacOS" / "Godot").is_file())
        record = pins.installed(self.co, "new_client")
        self.assertEqual((record["version"], record["game"]), ("0.36c", "0.36b"))

    def test_mtimes_preserved(self):
        self.install()
        mtime = (self.co.new_client_project / "content" / "zone2.png").stat().st_mtime
        self.assertEqual(time.localtime(mtime)[:6], STAMP)

    def test_bad_part_hash_stops_before_extract(self):
        name = self.pin["parts"][1]["name"]
        self.served[URL + name] = b"corrupt"
        with self.assertRaises(DaocError) as cm:
            self.install()
        self.assertIn(name, cm.exception.msg)
        self.assertFalse((self.co.downloads / "v0.36c" / name).exists())
        self.assertFalse((self.co.downloads / "v0.36c" / (name + ".done")).exists())
        self.assertFalse(self.co.new_client_root.exists())

    def test_resume_skips_done_parts(self):
        second = URL + self.pin["parts"][1]["name"]
        self.fetch.fail.add(second)
        with self.assertRaises(DaocError):
            self.install()
        self.fetch.fail.clear()
        self.fetch.urls.clear()
        self.install()
        self.assertNotIn(URL + self.pin["parts"][0]["name"], self.fetch.urls)
        self.assertIn(second, self.fetch.urls)
        self.assertEqual(len(self.files()), 4)
        self.assertEqual(list((self.co.downloads / "v0.36c").glob("*.done")), [])

    def test_interrupted_part_not_marked_done(self):
        real = newclient.extract_filtered
        calls = []

        def flaky(zip_path, root_folder, dest):
            calls.append(zip_path.name)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real(zip_path, root_folder, dest)

        with mock.patch.object(newclient, "extract_filtered", flaky), self.assertRaises(KeyboardInterrupt):
            self.install()
        second = self.pin["parts"][1]["name"]
        self.assertFalse((self.co.downloads / "v0.36c" / (second + ".done")).exists())
        self.assertFalse(self.co.new_client_root.exists())
        self.install()
        self.assertEqual(len(self.files()), 4)

    def test_lost_staging_restarts_every_part(self):
        self.fetch.fail.add(URL + self.pin["parts"][2]["name"])
        with self.assertRaises(DaocError):
            self.install()
        shutil.rmtree(self.co.root / "dist" / ".new-client.new")
        self.fetch.fail.clear()
        self.fetch.urls.clear()
        self.install()
        self.assertEqual(len([u for u in self.fetch.urls if u.startswith(URL)]), 3)
        self.assertEqual(len(self.files()), 4)

    def test_swap_replaces_previous_install_atomically(self):
        self.install()
        (self.co.new_client_project / "stale.txt").write_text("old")
        pins.record_installed(self.co, "new_client", {"version": "0.36c", "game": "0.36b", "parts": []})
        self.install()
        self.assertNotIn("stale.txt", self.files())
        self.assertFalse((self.co.root / "dist" / ".new-client.old").exists())
        self.assertFalse((self.co.root / "dist" / ".new-client.new").exists())

    def test_installed_pin_is_kept(self):
        self.install()
        self.fetch.urls.clear()
        err = self.install()
        self.assertEqual(self.fetch.urls, [])
        self.assertIn("new client already installed", err)

    def test_stage_only_leaves_the_install_alone(self):
        self.install(download_only=True)
        self.assertFalse(self.co.new_client_root.exists())
        self.fetch.urls.clear()
        self.install()
        self.assertEqual([u for u in self.fetch.urls if u.startswith(URL)], [])
        self.assertEqual(len(self.files()), 4)

    def test_disk_check_refuses_with_needed_gb(self):
        usage = SimpleNamespace(total=0, used=0, free=1024 ** 3)
        with mock.patch.object(newclient.shutil, "disk_usage", return_value=usage), \
                self.assertRaises(DaocError) as cm:
            self.install()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("2.0 GB", cm.exception.msg)  # 1000 bytes + a part + the 2 GB margin, rounded
        self.assertEqual(self.fetch.urls, [])

    def test_refused_before_036(self):
        with self.assertRaises(DaocError) as cm:
            self.install(Game("0.35", "sluaghbinder"))
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("the new client exists from 0.36", cm.exception.msg)

    def test_zip_slip_refused(self):
        bad = zip_bytes({f"{ROOT}/new-client/godot/../../../escape.txt": b"x"})
        path = Path(self.co.root) / "bad.zip"
        path.write_bytes(bad)
        dest = Path(self.co.root) / "dest"
        with self.assertRaises(DaocError):
            newclient.extract_filtered(path, ROOT, dest)
        self.assertFalse((self.co.root / "escape.txt").exists())

    def test_entry_outside_root_refused(self):
        path = Path(self.co.root) / "bad.zip"
        path.write_bytes(zip_bytes({f"{ROOT}/new-client/godot/a": b"a", "elsewhere/b": b"b"}))
        dest = Path(self.co.root) / "dest"
        with self.assertRaises(DaocError) as cm:
            newclient.extract_filtered(path, ROOT, dest)
        self.assertIn("elsewhere/b", cm.exception.msg)
        self.assertFalse(dest.exists())

    def test_install_sets_default_client_new(self):
        selection.save(self.co, Selection(GAME, "original"))
        with mock.patch.object(newclient.release, "download", self.fetch):
            code, _, err = run_cli(["client", "install", "--client", "new"], self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(selection.load(self.co).client, "new")
        self.assertEqual(len(self.files()), 4)

    def test_wine_flag_is_for_the_original_client(self):
        code, _, err = run_cli(["client", "install", "--client", "new", "--wine", "arm64"], self.root)
        self.assertEqual(code, 2)
        self.assertIn("--wine applies to the original client", err)

    def client_update(self, latest):
        selection.save(self.co, Selection(GAME, "new"))
        with mock.patch.object(newclient.release, "download", self.fetch), \
                mock.patch("daoc_cli.updates.resolve_latest",
                           side_effect=lambda co, group, version=None: dict(latest)):
            return run_cli(["client", "update"], self.root)

    def test_update_moves_the_default_new_client_to_its_latest_assets(self):
        self.install()
        # Upstream replaced a part of the same release tag.
        name = self.pin["parts"][2]["name"]
        data = zip_bytes(dict(part_entries(3), **{f"{ROOT}/new-client/godot/content/zone3.png": b"redone"}))
        self.served[URL + name] = data
        latest = dict(self.pin, parts=[dict(p) for p in self.pin["parts"]])
        latest["parts"][2].update(bytes=len(data), sha256=sha(data))
        self.fetch.urls.clear()
        code, _, err = self.client_update(latest)
        self.assertEqual(code, 0, err)
        self.assertEqual((self.co.new_client_project / "content" / "zone3.png").read_bytes(), b"redone")
        self.assertEqual(pins.local(self.co, "new_client", "0.36")["parts"][2]["sha256"], sha(data))
        self.assertFalse(self.co.client_root.exists())
        self.assertTrue(all(u.startswith(URL) for u in self.fetch.urls), self.fetch.urls)

    def test_update_of_a_current_new_client_downloads_nothing(self):
        self.install()
        self.fetch.urls.clear()
        code, _, err = self.client_update(self.pin)
        self.assertEqual(code, 0, err)
        self.assertIn("new client already at 0.36c", err)
        self.assertEqual(self.fetch.urls, [])

    def test_update_without_the_new_client_installed_is_refused(self):
        code, _, err = self.client_update(self.pin)
        self.assertEqual(code, 2)
        self.assertIn("daoc client install --client new", err)
        self.assertEqual(self.fetch.urls, [])


PATCH_URL = "https://example.invalid/0.37c/"
PATCH_ROOT = "OfflineDAoC-v0.37c-client-patch"


class UpdateReleaseInstallTest(unittest.TestCase):
    """0.37c: the 0.36c base, then the update's files checked against its patch.json."""
    install = NewClientInstallTest.install
    files = NewClientInstallTest.files

    def setUp(self):
        NewClientInstallTest.setUp(self)  # the 0.36c base release as self.pin
        self.base = {k: v for k, v in self.pin.items() if k != "godot"}
        files = {"content/zone2.png": b"zone 2, 0.37", "content/new.png": b"new in 0.37"}
        self.listed = [
            {"Path": "new-client/godot/content/zone2.png", "Sha256": sha(files["content/zone2.png"]),
             "Bytes": len(files["content/zone2.png"]), "From": [sha(b"zone 2")]},
            {"Path": "new-client/godot/content/new.png", "Sha256": sha(files["content/new.png"]),
             "Bytes": len(files["content/new.png"]), "From": ["absent"]},
            {"Path": "new-client/VERSION.txt", "Sha256": sha(b"0.37c"), "Bytes": 5, "From": [sha(b"0.36c")]},
        ]
        self.patch_files = files
        self.serve_update()

    def serve_update(self, listed=None, extra=None):
        patch = {"Version": "0.37", "Kind": "new-client", "Files": listed or self.listed, "Remove": []}
        part1 = {f"{PATCH_ROOT}/patch.json": json.dumps(patch).encode(),
                 f"{PATCH_ROOT}/files/new-client/godot/content/zone2.png": self.patch_files["content/zone2.png"],
                 f"{PATCH_ROOT}/patcher/OfflineDaoc.Patcher.dll": b"windows"}
        part2 = dict({f"{PATCH_ROOT}/files/new-client/godot/content/new.png": self.patch_files["content/new.png"],
                      f"{PATCH_ROOT}/files/new-client/VERSION.txt": b"0.37c"}, **(extra or {}))
        parts = {f"{PATCH_ROOT}-part0{n}.zip": zip_bytes(p) for n, p in ((1, part1), (2, part2))}
        self.served.update({PATCH_URL + name: data for name, data in parts.items()})
        godot = self.pin["godot"]
        self.pin = {
            "release_url": PATCH_URL, "version": "0.37c", "manifest_asset": "download-manifest.json",
            "root_folder": PATCH_ROOT, "unpacked_bytes": 100,
            "parts": [{"name": n, "bytes": len(d), "sha256": sha(d)} for n, d in parts.items()],
            "base": self.base, "godot": godot,
        }
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["versions"]["0.36"]["new_client"] = self.pin
        path.write_text(json.dumps(manifest))
        self.co = Checkout(self.root)

    def test_update_lands_on_the_base(self):
        self.install()
        self.assertEqual(self.files(), ["content/new.png", "content/zone1.png", "content/zone2.png",
                                        "content/zone3.png", "project.godot"])
        project = self.co.new_client_project
        self.assertEqual((project / "content" / "zone2.png").read_bytes(), b"zone 2, 0.37")
        self.assertEqual((project / "content" / "zone3.png").read_bytes(), b"zone 3")
        self.assertEqual(time.localtime((project / "content" / "new.png").stat().st_mtime)[:6], STAMP)
        self.assertEqual(pins.installed(self.co, "new_client")["version"], "0.37c")
        # Base parts from the base release, update parts from the update's.
        self.assertEqual([u.rsplit("/", 1)[0] + "/" for u in self.fetch.urls if u.endswith(".zip")
                          and u != GODOT_URL], [URL] * 3 + [PATCH_URL] * 2)
        self.assertEqual(list(self.co.downloads.glob("v*/*")), [])

    def test_a_base_file_that_is_not_the_released_one_is_refused(self):
        listed = [dict(self.listed[0], From=[sha(b"another zone 2")]), *self.listed[1:]]
        self.serve_update(listed=listed)
        with self.assertRaises(DaocError) as cm:
            self.install()
        self.assertIn("content/zone2.png is not the file this update replaces", cm.exception.msg)
        self.assertFalse(self.co.new_client_root.exists())

    def test_a_file_patch_json_does_not_list_is_refused_before_writing(self):
        self.serve_update(extra={f"{PATCH_ROOT}/files/new-client/godot/content/sneaky.png": b"x"})
        with self.assertRaises(DaocError) as cm:
            self.install()
        self.assertIn("content/sneaky.png, which its patch.json does not list", cm.exception.msg)
        staged = self.co.new_client_root.parent / ".new-client.new" / "godot" / "content"
        self.assertFalse((staged / "new.png").exists())
        self.assertFalse(self.co.new_client_root.exists())

    def test_rerun_after_an_interrupted_update_finishes_it(self):
        self.fetch.fail.add(PATCH_URL + self.pin["parts"][1]["name"])
        with self.assertRaises(DaocError):
            self.install()
        self.fetch.fail.clear()
        self.fetch.urls.clear()
        self.install()
        # Only the update part that never arrived is fetched again; patch.json came with part 1.
        self.assertEqual([u for u in self.fetch.urls if u != GODOT_URL], [PATCH_URL + self.pin["parts"][1]["name"]])
        self.assertEqual((self.co.new_client_project / "content" / "new.png").read_bytes(), b"new in 0.37")



if __name__ == "__main__":
    unittest.main()
