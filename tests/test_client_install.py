"""daoc client install: release fetch/verify/extract and the install steps,
with synthetic files, a fake downloader and stub wine binaries (no network)."""
import io
import json
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import unittest
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls
from tests.test_client_patch import SPEC, patched_bytes, pristine_bytes, sha

from daoc_cli import client, client_patch, pins, release
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

URL = "https://example.invalid/rel/"
ROOT_FOLDER = "OfflineDAoC-vT"


def make_release(entries=None):
    """(pin, {url: bytes}) for a zip of entries split into 3 parts."""
    if entries is None:
        entries = {f"{ROOT_FOLDER}/runtime/client-opendaoc/app/game.dll": b"dll",
                   f"{ROOT_FOLDER}/readme.txt": b"hello"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    archive = buf.getvalue()
    third = len(archive) // 3 + 1
    chunks = [archive[i:i + third] for i in range(0, len(archive), third)]
    parts = [{"name": f"OfflineDAoC-vT.zip.{i + 1:03d}", "bytes": len(c), "sha256": sha(c)}
             for i, c in enumerate(chunks)]
    pin = {"release_url": URL, "version": "T", "manifest_asset": "download-manifest.json",
           "root_folder": ROOT_FOLDER, "archive_sha256": sha(archive),
           "archive_bytes": len(archive), "parts": parts}
    manifest = {"Version": "T", "RootFolder": ROOT_FOLDER, "ArchiveSHA256": sha(archive),
                "ArchiveBytes": len(archive),
                "Parts": [{"Name": p["name"], "Bytes": p["bytes"], "SHA256": p["sha256"]}
                          for p in parts]}
    served = {URL + "download-manifest.json": json.dumps(manifest).encode()}
    served.update({URL + p["name"]: c for p, c in zip(parts, chunks)})
    return pin, served


class FakeDownloads:
    def __init__(self, served):
        self.served = served
        self.urls = []

    def __call__(self, url, dest):
        self.urls.append(url)
        dest.write_bytes(self.served[url])


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "downloads" / "vT"
        self.dist = Path(self.tmp.name) / "dist"

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, pin, fake):
        with redirect_stderr(io.StringIO()):
            archive = release.download_release(pin, self.cache, fetch_url=fake)
            return release.extract(archive, pin["root_folder"], self.dist)

    def test_fetch_verifies_joins_and_extracts(self):
        pin, served = make_release()
        fake = FakeDownloads(served)
        target = self.fetch(pin, fake)
        self.assertEqual(target, self.dist / ROOT_FOLDER)
        self.assertEqual((target / "readme.txt").read_bytes(), b"hello")
        self.assertEqual(len(fake.urls), 4)
        # A second run reuses the verified cache.
        shutil.rmtree(target)
        again = FakeDownloads(served)
        self.fetch(pin, again)
        self.assertEqual(again.urls, [])

    def test_corrupted_part_is_rejected(self):
        pin, served = make_release()
        bad = URL + pin["parts"][1]["name"]
        served[bad] = bytes([served[bad][0] ^ 0xFF]) + served[bad][1:]
        with self.assertRaises(DaocError) as cm:
            self.fetch(pin, FakeDownloads(served))
        self.assertIn(pin["parts"][1]["name"], cm.exception.msg)
        self.assertIn("SHA-256", cm.exception.msg)
        self.assertFalse((self.dist / ROOT_FOLDER).exists())
        self.assertFalse((self.cache / "OfflineDAoC-vT.zip").exists())

    def test_corrupted_cached_part_is_downloaded_again(self):
        pin, served = make_release()
        self.cache.mkdir(parents=True)
        name = pin["parts"][0]["name"]
        (self.cache / name).write_bytes(b"\x00" * pin["parts"][0]["bytes"])
        fake = FakeDownloads(served)
        self.fetch(pin, fake)
        self.assertIn(URL + name, fake.urls)
        self.assertEqual((self.cache / name).read_bytes(), served[URL + name])

    def test_release_manifest_differing_from_pin_is_fatal(self):
        pin, served = make_release()
        pin = dict(pin, archive_sha256="0" * 64)
        fake = FakeDownloads(served)
        with self.assertRaises(DaocError) as cm:
            self.fetch(pin, fake)
        self.assertIn("ArchiveSHA256", cm.exception.msg)
        self.assertEqual(fake.urls, [URL + "download-manifest.json"])

    def test_entry_outside_root_folder_is_refused(self):
        pin, served = make_release({f"{ROOT_FOLDER}/a": b"a", "elsewhere/b": b"b"})
        with self.assertRaises(DaocError) as cm:
            self.fetch(pin, FakeDownloads(served))
        self.assertIn("unexpected zip entry", cm.exception.msg)
        self.assertFalse((self.dist / "elsewhere").exists())

    def test_part_name_outside_the_cache_is_refused_before_touching_it(self):
        victim = self.cache.parent / "victim"  # where "../victim" from the cache lands
        victim.parent.mkdir(parents=True)
        for bad in ("../victim", str(victim)):
            victim.write_bytes(b"keep")
            pin, served = make_release()
            manifest = json.loads(served[URL + "download-manifest.json"])
            manifest["Parts"][0]["Name"] = bad
            served[URL + "download-manifest.json"] = json.dumps(manifest).encode()
            pin["parts"][0] = dict(pin["parts"][0], name=bad)
            fake = FakeDownloads(served)
            with self.assertRaises(DaocError) as cm:
                self.fetch(pin, fake)
            self.assertIn("not a plain file name", cm.exception.msg)
            self.assertEqual(victim.read_bytes(), b"keep")
            self.assertEqual(fake.urls, [URL + "download-manifest.json"])
            shutil.rmtree(self.cache)

    def test_cached_part_symlinked_outside_the_cache_is_refused(self):
        pin, served = make_release()
        victim = Path(self.tmp.name) / "victim"
        victim.write_bytes(b"keep")
        self.cache.mkdir(parents=True)
        (self.cache / pin["parts"][0]["name"]).symlink_to(victim)
        with self.assertRaises(DaocError) as cm:
            self.fetch(pin, FakeDownloads(served))
        self.assertIn("resolves outside", cm.exception.msg)
        self.assertEqual(victim.read_bytes(), b"keep")

    def test_existing_destination_is_refused(self):
        pin, served = make_release()
        (self.dist / ROOT_FOLDER).mkdir(parents=True)
        with self.assertRaises(DaocError) as cm:
            self.fetch(pin, FakeDownloads(served))
        self.assertIn("already exists", cm.exception.msg)


WINE_STUB = """\
echo "$WINEPREFIX" >> "$(dirname "$0")/prefix.log"
case "$1 $2" in
  "wineboot -i")
    mkdir -p "$WINEPREFIX/drive_c/users/crossover"
    touch "$WINEPREFIX/system.reg"
    ln -s /tmp "$WINEPREFIX/drive_c/users/crossover/Documents" ;;
  "wineboot -u")
    [ -z "$WINE_FAIL" ] || { echo "wine says boom"; exit 3; }
    # Like wineserver: a child that outlives wineboot with its stdout. Its pid
    # is recorded so the test can stop it.
    if [ -n "$WINE_LINGER" ]; then
      sleep 20 &
      echo $! > "$(dirname "$0")/linger.pid"
    fi ;;
esac
"""


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_checkout(self.tmp.name)
        self.co = Checkout(self.root)
        # install always targets <root>/dist/wine and <root>/dist/prefix.
        self.wine_home = self.co.root / "dist" / "wine"
        self.stubs = path_stubs(self.wine_home, {"wine": WINE_STUB, "wineserver": ""})
        (self.wine_home / "bin").symlink_to("stubs")
        self.prefix = self.co.root / "dist" / "prefix"
        launcher = self.root / "client" / "DAoCLauncher.app" / "Contents" / "MacOS"
        launcher.mkdir(parents=True)
        (launcher / "launch").write_text("#!/bin/sh\n")
        self.co.app_dir.mkdir(parents=True)
        pins.record_installed(self.co, "client", pins.shipped(self.co, "client"))
        self.env = {"DAOC_WINE_HOME": None, "DAOC_WINEPREFIX": None,
                    "USER": "olduser", "WINE_FAIL": None, "WINE_LINGER": None}

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, **env):
        with mock.patch.object(client, "_requirements"):
            return run_cli(["client", "install"], self.root, dict(self.env, **env))

    def test_fresh_prefix_patch_and_launcher(self):
        dll = self.co.app_dir / "game.dll"
        dll.write_bytes(pristine_bytes())
        with mock.patch.dict(client_patch.PROVEN_BUILDS, {sha(pristine_bytes()): SPEC}):
            code, out, err = self.install()
        self.assertEqual(code, 0, err)
        self.assertIn("wine already installed", err)
        self.assertIn("OfflineDAoC already installed", err)
        self.assertEqual(dll.read_bytes(), patched_bytes())
        self.assertEqual((self.co.app_dir / "game.dll.orig").read_bytes(), pristine_bytes())
        calls = [c[:3] for c in stub_calls(self.stubs)]
        self.assertEqual(calls, [["wine", "wineboot", "-i"], ["wine", "reg", "add"],
                                 ["wineserver", "-w"], ["wine", "wineboot", "-u"],
                                 ["wineserver", "-w"]])
        self.assertEqual(stub_calls(self.stubs)[1][3:],
                         ["HKCU\\Software\\Wine", "/v", "Version", "/d", "win10", "/f"])
        prefixes = set((self.stubs / "prefix.log").read_text().split())
        self.assertEqual(prefixes, {str(self.prefix)})
        documents = self.prefix / "drive_c/users/crossover/Documents"
        self.assertTrue(documents.is_dir() and not documents.is_symlink())
        self.assertTrue((self.co.launcher_app / "Contents/MacOS/launch").is_file())

    def test_rerun_skips_finished_steps_and_carries_settings_over(self):
        (self.co.app_dir / "game.dll").write_bytes(b"patched")
        (self.co.app_dir / "game.dll.orig").write_bytes(b"pristine")
        (self.prefix).mkdir()
        (self.prefix / "system.reg").touch()
        ea = Path("drive_c/users/olduser/AppData/Roaming/Electronic Arts")
        (self.prefix / ea).mkdir(parents=True)
        (self.prefix / ea / "settings.ini").write_text("x=1\n")
        self.co.launcher_app.mkdir(parents=True)
        (self.co.launcher_app / "stale").touch()
        code, out, err = self.install()
        self.assertEqual(code, 0, err)
        for line in ("wine already installed", "OfflineDAoC already installed",
                     "client already patched", "wine prefix already initialized"):
            self.assertIn(line, err)
        self.assertEqual((self.co.app_dir / "game.dll").read_bytes(), b"patched")
        self.assertEqual([c[:3] for c in stub_calls(self.stubs)],
                         [["wine", "wineboot", "-u"], ["wineserver", "-w"]])
        copied = self.prefix / "drive_c/users/crossover/AppData/Roaming/Electronic Arts"
        self.assertEqual((copied / "settings.ini").read_text(), "x=1\n")
        self.assertFalse((self.co.launcher_app / "stale").exists())
        self.assertEqual(out, "")

    def test_wine_failure_replays_its_output(self):
        (self.co.app_dir / "game.dll.orig").write_bytes(b"pristine")
        self.prefix.mkdir()
        (self.prefix / "system.reg").touch()
        code, out, err = self.install(WINE_FAIL="1")
        self.assertEqual(code, 1)
        self.assertIn("wine says boom", err)
        self.assertIn("daoc: wine wineboot failed (exit 3)", err)

    def test_wineboot_output_goes_to_a_file_not_a_pipe(self):
        (self.co.app_dir / "game.dll.orig").write_bytes(b"pristine")
        self.prefix.mkdir()
        (self.prefix / "system.reg").touch()
        started = time.monotonic()
        code, out, err = self.install(WINE_LINGER="1")
        elapsed = time.monotonic() - started
        self.addCleanup(self.stop, int((self.stubs / "linger.pid").read_text()))
        self.assertEqual(code, 0, err)
        self.assertLess(elapsed, 10)

    @staticmethod
    def stop(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def test_unproven_client_stops_the_install(self):
        dll = self.co.app_dir / "game.dll"
        dll.write_bytes(pristine_bytes())
        code, out, err = self.install()
        self.assertEqual(code, 2)
        self.assertIn("not a Proven build", err)
        self.assertEqual(dll.read_bytes(), pristine_bytes())
        self.assertEqual(stub_calls(self.stubs), [])

    def pin_release(self):
        """Make a release holding a pristine game.dll the Shipped client pin;
        returns its served files."""
        pin, served = make_release({f"{ROOT_FOLDER}/{client.GAME_DLL}": pristine_bytes(),
                                    f"{ROOT_FOLDER}/readme.txt": b"pinned"})
        pin = dict(pin, game_dll_sha256=sha(pristine_bytes()))
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["client"] = pin
        manifest_path.write_text(json.dumps(manifest))
        return served

    def test_install_from_another_release_is_replaced_with_the_pin(self):
        # A pull moved the Shipped pin: the install is still the other release
        # and install brings it back to the pin.
        served = self.pin_release()
        (self.co.app_dir / "game.dll.orig").write_bytes(b"other pristine")
        pins.record_installed(self.co, "client", {"version": "0.36"})
        self.prefix.mkdir()
        (self.prefix / "system.reg").touch()
        with mock.patch.dict(client_patch.PROVEN_BUILDS, {sha(pristine_bytes()): SPEC}), \
                mock.patch.object(release, "download", FakeDownloads(served)):
            code, out, err = self.install()
        self.assertEqual(code, 0, err)
        self.assertIn("replacing OfflineDAoC 0.36 with the pinned vT", err)
        self.assertIn("client already patched", err)
        self.assertEqual((self.co.client_root / "readme.txt").read_bytes(), b"pinned")
        self.assertEqual((self.co.app_dir / "game.dll").read_bytes(), patched_bytes())
        self.assertEqual(pins.installed(self.co, "client")["version"], "T")

        code, out, err = self.install()
        self.assertEqual(code, 0, err)
        self.assertIn("OfflineDAoC already installed", err)

    def test_fresh_install_killed_while_extracting_recovers_on_rerun(self):
        served = self.pin_release()
        shutil.rmtree(self.co.client_root)
        self.prefix.mkdir()
        (self.prefix / "system.reg").touch()
        extract = release.extract

        def killed(archive, root_folder, dest_dir):
            extract(archive, root_folder, dest_dir)
            raise DaocError("killed")  # the extracted tree stays where the kill left it

        with mock.patch.dict(client_patch.PROVEN_BUILDS, {sha(pristine_bytes()): SPEC}), \
                mock.patch.object(release, "download", FakeDownloads(served)):
            with mock.patch.object(release, "extract", killed):
                code, out, err = self.install()
            self.assertEqual(code, 1)
            self.assertFalse(self.co.client_root.exists())
            code, out, err = self.install()
        self.assertEqual(code, 0, err)
        self.assertEqual((self.co.client_root / "readme.txt").read_bytes(), b"pinned")
        self.assertEqual((self.co.app_dir / "game.dll").read_bytes(), patched_bytes())
        self.assertEqual(pins.installed(self.co, "client")["version"], "T")
        self.assertEqual(sorted(p.name for p in self.co.client_root.parent.iterdir()),
                         ["DAoCLauncher.app", "OfflineDAoC", "prefix", "wine"])

    def test_wine_and_prefix_overrides_are_never_install_targets(self):
        shutil.rmtree(self.wine_home)  # no Wine installed yet
        outside_wine = Path(self.tmp.name) / "my-wine"
        outside_wine.mkdir()
        (outside_wine / "keep.txt").write_text("mine\n")
        outside_prefix = Path(self.tmp.name) / "my-prefix"
        outside_prefix.mkdir()
        # A cached Wine tarball (root wine/) whose bin/ holds the stubs.
        bundled = path_stubs(Path(self.tmp.name) / "bundle", {"wine": WINE_STUB,
                                                              "wineserver": ""})
        self.co.downloads.mkdir()
        tarball = self.co.downloads / "wine-test.tar.xz"
        with tarfile.open(tarball, "w:xz") as tf:
            tf.add(bundled, arcname="wine/bin")
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["wine"] = dict(manifest["wine"], tarball=tarball.name,
                                sha256=sha(tarball.read_bytes()))
        manifest_path.write_text(json.dumps(manifest))
        (self.co.app_dir / "game.dll.orig").write_bytes(b"pristine")
        code, out, err = self.install(DAOC_WINE_HOME=str(outside_wine),
                                      DAOC_WINEPREFIX=str(outside_prefix))
        self.assertEqual(code, 0, err)
        self.assertEqual([p.name for p in outside_wine.iterdir()], ["keep.txt"])
        self.assertEqual((outside_wine / "keep.txt").read_text(), "mine\n")
        self.assertEqual(list(outside_prefix.iterdir()), [])
        self.assertTrue((self.wine_home / "bin" / "wine").is_file())
        self.assertTrue((self.prefix / "system.reg").is_file())
        prefixes = set((self.wine_home / "bin" / "prefix.log").read_text().split())
        self.assertEqual(prefixes, {str(self.prefix)})
        self.assertEqual([c[:3] for c in stub_calls(bundled)][0], ["wine", "wineboot", "-i"])


class RequirementsTest(unittest.TestCase):
    def check(self, product_version):
        def run(argv, **kwargs):
            out = product_version + "\n" if argv[0] == client.SW_VERS else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        with mock.patch.object(client.platform, "system", return_value="Darwin"), \
                mock.patch.object(client.platform, "machine", return_value="arm64"), \
                mock.patch.object(client.proc, "run", side_effect=run), \
                mock.patch.object(client.shutil, "which", return_value="/usr/bin/curl"):
            client._requirements()

    def test_macos_older_than_26_is_refused(self):
        for old in ("15.7.4", "9.9"):
            with self.assertRaises(DaocError) as cm:
                self.check(old)
            self.assertIn("macOS 26 or later required", cm.exception.msg)
            self.assertIn(old, cm.exception.msg)

    def test_macos_26_and_later_pass(self):
        for ok in ("26", "26.0", "26.4.1", "27.0.1"):
            self.check(ok)

    def test_unreadable_version_is_an_error(self):
        with self.assertRaises(DaocError) as cm:
            self.check("")
        self.assertIn("cannot read the macOS version", cm.exception.msg)



if __name__ == "__main__":
    unittest.main()
