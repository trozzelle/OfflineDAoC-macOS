"""daoc client update: the Proven-build gate, the running refusal, and the
graphics carry-over around the replace, including resuming an interrupted one.

The release is a small synthetic zip served by a fake downloader, the GitHub
lookup and the running-client probe are stubbed, and daoc-gfx is a fake that
keeps its state in a JSON file inside the client's app folder (so the replace
loses it, as it loses the real patches) and logs every call.
"""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli
from tests.test_client_install import ROOT_FOLDER, FakeDownloads, make_release
from tests.test_client_patch import SPEC, patched_bytes, pristine_bytes, sha

from daoc_cli import client, client_patch, client_runtime, graphics, pins, release, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

FAKE_GFX = r'''
import json, sys
from pathlib import Path

here = Path(__file__).resolve().parent
args, opts = sys.argv[1:], {}
while args and args[0].startswith("--"):
    opts[args[0]], args = args[1], args[2:]
with (here / "calls.log").open("a") as f:
    f.write(json.dumps({"args": args, "opts": opts}) + "\n")
mode = (here / "mode").read_text() if (here / "mode").exists() else ""
if mode == "no-json" and args == ["status", "--json"]:
    sys.exit("usage: daoc-gfx ...\ndaoc-gfx: error: unrecognized arguments: --json")
if mode and " ".join(args).startswith(mode):
    sys.exit(f"daoc-gfx: {mode} broke")

path = Path(opts["--app"]) / "fake-gfx.json"
state = json.loads(path.read_text()) if path.exists() else {
    "display": {"retina": "off", "srgb": "off"}, "level": None, "components": []}
comps = state["components"]


def opt(name):
    return [args[i + 1] for i, a in enumerate(args) if a == name]


if args == ["status", "--json"]:
    tex = {s for _, s in comps}
    patches = dict(state["display"])
    patches["textures"] = ("not installed" if not comps else "on" if tex == {"pack active"}
                           else "off" if tex == {"originals active"} else "partly on")
    patches["anisotropy"] = "on" if state["level"] else "off"
    patches.update(state.get("override", {}))  # states enable/disable never produce
    print(json.dumps({
        "schema": 1, "patches": patches, "anisotropy_level": state["level"],
        "mtld3d_conf": state.get("conf")
        or ("daoc-gfx" if state["display"]["srgb"] == "on" else "none"),
        "textures": {"components": [{"name": n, "state": s} for n, s in comps],
                     "pending": None}}))
    sys.exit(0)
if args[0] in ("enable", "disable"):
    on = args[0] == "enable"
    for p in [a for a in args[1:] if not a.isdigit() and a != "--level"]:
        if p in state["display"]:
            state["display"][p] = "on" if on else "off"
        elif p == "anisotropy":
            state["level"] = int((opt("--level") or ["16"])[0]) if on else None
        elif p == "textures" and not on:
            comps[:] = [[n, "originals active"] for n, _ in comps]
elif args[:2] == ["textures", "export"]:
    out = Path(args[2])
    if out.exists() and any(out.iterdir()):
        sys.exit("daoc-gfx: export folder not empty")
    for n, _ in comps:
        (out / n).mkdir(parents=True)
        (out / n / "tex.dds").write_text(n)
elif args[:2] == ["textures", "install"]:
    src = Path(opt("--from-dir")[0])
    comps[:] = [[d.name, "pack active"] for d in sorted(src.iterdir())
                if (d / "tex.dds").read_text() == d.name]
elif args[:2] == ["textures", "use"]:
    names, live = opt("-c"), "originals active" if args[2] == "original" else "pack active"
    comps[:] = [[n, live if n in names else s] for n, s in comps]
else:
    sys.exit(f"daoc-gfx: unexpected {args}")
path.write_text(json.dumps(state))
print("ok")
'''

EVERY_STATE = {"display": {"retina": "off", "srgb": "on"}, "level": 8,
               "components": [["figures", "originals active"], ["zones", "pack active"]]}


class ClientUpdateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = make_checkout(tmp.name)
        self.co = Checkout(self.root)
        self.co.app_dir.mkdir(parents=True)
        (self.co.app_dir / "game.dll").write_bytes(b"old dll")
        (self.co.client_root / "old-marker").touch()
        self.gfx_src = Path(tmp.name) / "gfx"
        self.gfx_src.mkdir()
        (self.gfx_src / "daoc-gfx").write_text(FAKE_GFX)
        (self.co.graphics_src / ".git").mkdir(parents=True)
        self.export = self.co.state / client.TEXTURES_EXPORT
        self.saved = self.co.state / client.CARRY_OVER
        self.pids = []
        self.dll = pristine_bytes()
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(graphics, "ensure_checkout",
                                              return_value=self.gfx_src))
        stack.enter_context(mock.patch.object(client_runtime, "game_pids",
                                              side_effect=lambda co: list(self.pids)))
        stack.enter_context(mock.patch.dict(client_patch.PROVEN_BUILDS,
                                            {sha(pristine_bytes()): SPEC}))
        self.latest = None

    def set_gfx(self, state):
        (self.co.app_dir / "fake-gfx.json").write_text(json.dumps(state))

    def gfx_state(self):
        return json.loads((self.co.app_dir / "fake-gfx.json").read_text())

    def gfx_calls(self):
        log = self.gfx_src / "calls.log"
        lines = log.read_text().splitlines() if log.exists() else []
        return [json.loads(line) for line in lines]

    def update(self):
        if self.latest is None:
            pin, served = make_release({f"{ROOT_FOLDER}/{client.GAME_DLL}": self.dll,
                                        f"{ROOT_FOLDER}/readme.txt": b"new release"})
            self.latest, self.served = dict(pin, game_dll_sha256=None), served
        self.downloads = FakeDownloads(self.served)
        with mock.patch.object(updates, "resolve_latest",
                               side_effect=lambda co, group: dict(self.latest)), \
                mock.patch.object(release, "download", self.downloads):
            return run_cli(["client", "update"], self.root)

    def assert_old_client_untouched(self):
        self.assertEqual((self.co.app_dir / "game.dll").read_bytes(), b"old dll")
        self.assertTrue((self.co.client_root / "old-marker").exists())
        self.assertIsNone(pins.local(self.co, "client"))

    def assert_new_client(self):
        self.assertEqual((self.co.client_root / "readme.txt").read_bytes(), b"new release")
        self.assertFalse((self.co.client_root / "old-marker").exists())
        self.assertEqual((self.co.app_dir / "game.dll").read_bytes(), patched_bytes())
        self.assertEqual((self.co.app_dir / "game.dll.orig").read_bytes(), pristine_bytes())
        dist = self.co.client_root.parent
        self.assertEqual(sorted(p.name for p in dist.iterdir()), ["OfflineDAoC"])
        local = pins.local(self.co, "client")
        self.assertEqual(local["version"], "T")
        self.assertEqual(local["game_dll_sha256"], sha(pristine_bytes()))

    def assert_carried_over(self, state):
        self.assertEqual(self.gfx_state(), state)
        self.assertFalse(self.saved.exists())
        self.assertFalse(self.export.exists())

    def test_every_state_round_trips(self):
        self.set_gfx(EVERY_STATE)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assert_new_client()
        self.assert_carried_over(EVERY_STATE)
        status = ["status", "--json"]
        self.assertEqual([c["args"] for c in self.gfx_calls()], [
            status,
            ["textures", "export", str(self.export)],
            ["disable", "srgb", "textures", "anisotropy"],
            status,
            ["enable", "srgb"],
            ["enable", "anisotropy", "--level", "8"],
            ["textures", "install", "--from-dir", str(self.export)],
            status,
            ["textures", "use", "original", "-c", "figures"],
            status,
        ])
        for call in self.gfx_calls():
            self.assertEqual(call["opts"]["--app"], str(self.co.app_dir))
            self.assertEqual(call["opts"]["--launcher"], str(self.co.launcher_app))

    def test_display_on_and_pack_active_round_trip_without_anisotropy(self):
        state = {"display": {"retina": "on", "srgb": "off"}, "level": None,
                 "components": [["zones", "pack active"]]}
        self.set_gfx(state)
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assert_carried_over(state)
        self.assertNotIn(["textures", "use", "original", "-c", "zones"],
                         [c["args"] for c in self.gfx_calls()])

    def test_nothing_on_needs_no_export_or_disable(self):
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assert_new_client()
        self.assertEqual([c["args"] for c in self.gfx_calls()], [["status", "--json"]] * 3)
        self.assertFalse(self.saved.exists())

    def test_unproven_build_stops_before_any_change(self):
        self.dll = b"some other game.dll"
        self.set_gfx(EVERY_STATE)
        code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn(f"daoc: T's game.dll ({sha(self.dll)[:12]}) is not a Proven build; "
                      "it needs a shipped update", err)
        self.assert_old_client_untouched()
        self.assertEqual(self.gfx_calls(), [])
        self.assertEqual(self.gfx_state(), EVERY_STATE)
        self.assertFalse(self.saved.exists())

    def test_running_client_is_refused(self):
        self.pids = [4242]
        self.set_gfx(EVERY_STATE)
        code, out, err = self.update()
        self.assertEqual(code, 2)
        self.assertIn("the client is running", err)
        self.assert_old_client_untouched()
        self.assertEqual(self.gfx_calls(), [])

    def test_already_at_latest(self):
        self.latest = pins.shipped(self.co, "client")
        pins.record_installed(self.co, "client", self.latest)
        self.served = {}
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn(f"daoc: client already at {self.latest['version']}", err)
        self.assertEqual(self.downloads.urls, [])
        self.assert_old_client_untouched()
        self.assertEqual(self.gfx_calls(), [])

    def test_install_behind_a_newer_shipped_pin_catches_up(self):
        # A pull brought a Shipped pin naming the latest release; the install is older.
        pin, self.served = make_release({f"{ROOT_FOLDER}/{client.GAME_DLL}": self.dll,
                                         f"{ROOT_FOLDER}/readme.txt": b"new release"})
        self.latest = dict(pin, game_dll_sha256=sha(self.dll))
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["client"] = self.latest
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        pins.record_installed(self.co, "client", {"version": "older"})
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("daoc: client update: OfflineDAoC older -> T", err)
        self.assertEqual((self.co.client_root / "readme.txt").read_bytes(), b"new release")
        self.assertEqual(pins.installed(self.co, "client")["version"], "T")
        self.assertIsNone(pins.local(self.co, "client"))

    def test_failed_restore_keeps_the_carry_over_and_a_rerun_resumes(self):
        self.set_gfx(EVERY_STATE)
        (self.gfx_src / "mode").write_text("enable anisotropy")
        code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("daoc-gfx enable anisotropy --level 8 failed", err)
        self.assertEqual(json.loads(self.saved.read_text())["anisotropy_level"], 8)
        self.assertEqual(sorted(p.name for p in self.export.iterdir()), ["figures", "zones"])
        self.assert_new_client()

        (self.gfx_src / "mode").unlink()
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("resuming an interrupted client update", err)
        self.assertIn("daoc: client already at T", err)
        self.assert_carried_over(EVERY_STATE)

    def test_failed_replace_keeps_the_carry_over_and_a_rerun_resumes(self):
        self.set_gfx(EVERY_STATE)
        with mock.patch.object(release, "extract", side_effect=DaocError("disk full")):
            code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("disk full", err)
        self.assertTrue(self.saved.exists())
        self.assertTrue(self.export.is_dir())
        self.assert_old_client_untouched()
        self.assertEqual(self.gfx_state()["level"], None)

        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("resuming an interrupted client update", err)
        self.assert_new_client()
        self.assert_carried_over(EVERY_STATE)

    def test_restore_difference_is_reported_and_kept(self):
        # A patch that only the old client's daoc-gfx state knows cannot come back.
        self.set_gfx(dict(EVERY_STATE, display={"retina": "off", "srgb": "on", "hdr": "on"}))
        code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("graphics did not come back as before the update", err)
        self.assertTrue(self.saved.exists())

    def test_interrupted_swap_is_undone(self):
        self.latest = pins.shipped(self.co, "client")
        pins.record_installed(self.co, "client", self.latest)
        old = self.co.client_root.parent / ".OfflineDAoC.old"
        self.co.client_root.rename(old)
        self.served = {}
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("put back the client", err)
        self.assert_old_client_untouched()
        self.assertFalse(old.exists())

    def test_pinned_daoc_gfx_without_status_json_is_refused(self):
        self.set_gfx(EVERY_STATE)
        (self.gfx_src / "mode").write_text("no-json")
        code, out, err = self.update()
        self.assertEqual(code, 1)
        self.assertIn("run `daoc graphics update` first", err)
        self.assert_old_client_untouched()
        self.assertFalse(self.saved.exists())

    def assert_refused_unchanged(self, state, message):
        self.set_gfx(state)
        code, out, err = self.update()
        self.assertEqual(code, 2, err)
        self.assertIn(message, err)
        self.assertEqual(self.gfx_state(), state)
        self.assertEqual([c["args"] for c in self.gfx_calls()], [["status", "--json"]])
        self.assertFalse(self.saved.exists())
        self.assertFalse(self.export.exists())
        self.assert_old_client_untouched()

    def test_partly_on_patch_is_refused_before_any_change(self):
        self.assert_refused_unchanged(
            dict(EVERY_STATE, override={"anisotropy": "partly on"}),
            "graphics patch anisotropy is partly on")

    def test_own_mtld3d_conf_is_refused_before_any_change(self):
        self.assert_refused_unchanged(
            dict(EVERY_STATE, conf="your own"),
            f"{self.co.app_dir / 'mtld3d.conf'} is your own file")

    def test_no_client_skips_the_carry_over(self):
        (self.co.app_dir / "game.dll").unlink()
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("no client game.dll yet; skipping the graphics carry-over", err)
        self.assert_new_client()
        self.assertEqual(self.gfx_calls(), [])

    def test_no_graphics_checkout_skips_the_carry_over(self):
        (self.co.graphics_src / ".git").rmdir()
        code, out, err = self.update()
        self.assertEqual(code, 0, err)
        self.assertIn("skipping the graphics carry-over", err)
        self.assert_new_client()
        self.assertEqual(self.gfx_calls(), [])


if __name__ == "__main__":
    unittest.main()
