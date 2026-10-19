"""updates: per-Version resolution against canned GitHub responses, and `update --check` changes nothing."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import games, pins, selection, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.selection import Selection

API = "https://api.github.com/repos/"
RAW = "https://raw.githubusercontent.com/"
NEW_SHA = "1234567890ab" + "c" * 28
FORK = "trozzelle/OfflineDAoC-macOS-server"


def marker(version):
    return f'        public const string OfflineDaocVersion = "{version}";\n'


def release_manifest(pin):
    return {
        "Version": pin["version"],
        "RootFolder": pin["root_folder"],
        "ArchiveSHA256": pin["archive_sha256"],
        "ArchiveBytes": pin["archive_bytes"],
        "Parts": [{"Name": p["name"], "Bytes": p["bytes"], "SHA256": p["sha256"]} for p in pin["parts"]],
    }


def newclient_manifest(pin):
    return {
        "Version": pin["version"], "Mode": "newclient", "BaseVersion": "0.36b",
        "RootFolder": pin["root_folder"], "UnpackedBytes": pin["unpacked_bytes"],
        "Parts": [{"Name": p["name"], "Bytes": p["bytes"], "SHA256": p["sha256"].upper(),
                   "UnpackedBytes": 1, "Files": 1} for p in pin["parts"]],
    }


def client_patch_manifest(pin, parts=None):
    """An update release's (0.37 on) download-manifest.json, its ClientPatch as pinned."""
    parts = parts or [{"Name": p["name"], "Bytes": p["bytes"], "SHA256": p["sha256"].upper(),
                       "UnpackedBytes": 0, "Files": 1} for p in pin["parts"]]
    parts[0]["UnpackedBytes"] = pin["unpacked_bytes"]
    return {
        "Version": pin["version"], "Mode": "patch", "BaseVersions": ["0.36"],
        "GamePatch": {"Release": pin["version"][:-1] + "b"},
        "ClientPatch": {"Release": pin["version"], "RootFolder": pin["root_folder"], "Parts": parts},
    }


def snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in sorted(root.rglob("*"))}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_checkout(self.tmp.name)
        self.co = Checkout(self.root)
        m = self.co.manifest
        self.gfx_api = API + m["graphics"]["repo"][len("https://github.com/"):] + "/commits/main"
        self.releases_api = API + "shadowofze/OfflineDAoC/releases?per_page=30"
        self.responses = {self.releases_api: [{"tag_name": t} for t in ("v0.36c", "v0.36b", "v0.36", "v0.35b")]}
        self.seen = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def select(self, game, client="original"):
        selection.save(self.co, Selection(games.parse(game), client))

    def server_api(self, version="0.36"):
        """Where the server pin of version resolves its branch head."""
        return API + FORK + "/commits/" + self.pin("server", version).get("branch", "main")

    def raw(self, sha, path="src/Admin.Host/AdminService.cs"):
        return f"{RAW}{FORK}/{sha}/{path}"

    def asset(self, pin):
        return pin["release_url"] + "download-manifest.json"

    def urlopen(self, req, timeout=None):
        url = req.full_url
        self.seen.append(url)
        answer = self.responses.get(url, 404)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "Not Found", {}, None)
        if isinstance(answer, str):
            return io.BytesIO(answer.encode())
        return io.BytesIO(json.dumps(answer).encode())

    def serve(self):
        return mock.patch.object(updates.urllib.request, "urlopen", self.urlopen)

    def pin(self, group, version):
        return pins.shipped(self.co, group, version)

    def serve_shipped(self, version="0.36", main=None, marked=None, gfx=None):
        """Latest == Shipped for every pin of version unless told otherwise."""
        sha = main or self.pin("server", version)["ref"]
        self.responses.update({
            self.server_api(version): {"sha": sha},
            self.raw(sha): marker(marked or version),
            self.gfx_api: {"sha": gfx or self.co.manifest["graphics"]["ref"]},
        })
        original = self.pin("original_client", version)
        self.responses[self.asset(original)] = release_manifest(original)
        if games.new_client_supported(self.co, version):
            new = self.pin("new_client", version)
            if new.get("base"):
                self.responses[self.asset(new)] = client_patch_manifest(new)
                self.responses[self.asset(new["base"])] = newclient_manifest(new["base"])
            else:
                self.responses[self.asset(new)] = newclient_manifest(new)


class ResolveLatestTest(Base):
    def test_server_follows_its_versions_branch(self) -> None:
        # 0.36's fixes land on macos-0.36 while main has moved on to a newer version.
        self.responses.update({self.server_api("0.36"): {"sha": NEW_SHA}, self.raw(NEW_SHA): marker("0.36"),
                               API + FORK + "/commits/main": {"sha": "f" * 40}, self.raw("f" * 40): marker("0.37")})
        with self.serve():
            server = updates.resolve_latest(self.co, "server", "0.36")
        self.assertEqual(server, dict(self.pin("server", "0.36"), ref=NEW_SHA))
        self.assertEqual(server["branch"], "macos-0.36")

    def test_marker_in_the_older_layout_keeps_navmesh_ref(self) -> None:
        self.responses.update({self.server_api("0.35"): {"sha": NEW_SHA},
                               self.raw(NEW_SHA, "src/GameServer/admin/AdminService.cs"): marker("0.35")})
        with self.serve():
            server = updates.resolve_latest(self.co, "server", "0.35")
        self.assertEqual(server["ref"], NEW_SHA)
        # The 0.35 branch has no navmeshes of its own: a Local pin must keep naming the commit that has.
        self.assertEqual(server["navmesh_ref"], self.pin("server", "0.35")["navmesh_ref"])

    def test_server_other_version_refused(self) -> None:
        self.responses.update({self.server_api("0.37"): {"sha": NEW_SHA}, self.raw(NEW_SHA): marker("0.38")})
        with self.serve(), self.assertRaises(updates.OtherVersion) as cm:
            updates.resolve_latest(self.co, "server", "0.37")
        self.assertEqual((cm.exception.found, cm.exception.code), ("0.38", 2))
        self.assertIn("server main is now 0.38; this daoc release doesn't support it yet", cm.exception.msg)

    def test_server_update_refuses_other_version_before_anything(self) -> None:
        self.select("0.37b")
        self.responses.update({self.server_api("0.37"): {"sha": NEW_SHA}, self.raw(NEW_SHA): marker("0.38")})
        with self.serve():
            code, _, err = run_cli(["server", "update"], self.root)
        self.assertEqual(code, 2)
        self.assertIn("server main is now 0.38", err)
        self.assertFalse((self.root / "upstream").exists())

    def test_marker_missing_refused(self) -> None:
        self.responses.update({self.server_api(): {"sha": NEW_SHA}})
        with self.serve(), self.assertRaises(updates.OtherVersion) as cm:
            updates.resolve_latest(self.co, "server", "0.36")
        self.assertIsNone(cm.exception.found)
        self.assertIn("names no game version", cm.exception.msg)

    def test_graphics_main_sha(self) -> None:
        self.responses = {self.gfx_api: {"sha": "f" * 40}}
        with self.serve():
            gfx = updates.resolve_latest(self.co, "graphics")
        self.assertEqual(gfx, {"repo": self.co.manifest["graphics"]["repo"], "ref": "f" * 40})

    def test_client_same_tag_unchanged_is_the_shipped_entry(self) -> None:
        self.serve_shipped()
        with self.serve():
            latest = updates.resolve_latest(self.co, "original_client", "0.36")
        self.assertEqual(latest, self.pin("original_client", "0.36"))

    def test_client_update_same_tag_changed_assets(self) -> None:
        shipped = self.pin("original_client", "0.36")
        changed = dict(shipped, archive_sha256="a" * 64)
        self.responses[self.asset(shipped)] = release_manifest(changed)
        with self.serve():
            latest = updates.resolve_latest(self.co, "original_client", "0.36")
        self.assertEqual(latest["archive_sha256"], "a" * 64)
        self.assertEqual(latest["version"], "0.36b")
        self.assertIsNone(latest["editions"])  # the editions' game.dll hashes must be re-derived
        self.assertFalse(pins.same("original_client", shipped, latest))

    def test_edition_and_newclient_manifests_parse(self) -> None:
        shipped = self.pin("original_client", "0.36")
        self.responses[self.asset(shipped)] = {"Version": "0.36b", "Mode": "edition", "BaseVersion": "0.36b"}
        with self.serve(), self.assertRaises(DaocError) as cm:
            updates.resolve_latest(self.co, "original_client", "0.36")
        self.assertIn("edition overlay", cm.exception.msg)

        new = self.pin("new_client", "0.36")
        self.responses[self.asset(new)] = newclient_manifest(new)
        with self.serve():
            latest = updates.resolve_latest(self.co, "new_client", "0.36")
        self.assertEqual(latest, new)
        self.assertEqual(latest["parts"][0]["sha256"], new["parts"][0]["sha256"].lower())
        self.assertEqual(latest["unpacked_bytes"], 33758711327)

    def test_update_release_new_client_round_trips(self) -> None:
        # 0.37c is an update of 0.36c: its ClientPatch and the base release re-read into the pin's shape.
        new = self.pin("new_client", "0.37")
        self.responses[self.asset(new)] = client_patch_manifest(new)
        self.responses[self.asset(new["base"])] = newclient_manifest(new["base"])
        with self.serve():
            self.assertEqual(updates.resolve_latest(self.co, "new_client", "0.37"), new)
        replaced = dict(new["parts"][1], sha256="a" * 64)
        self.responses[self.asset(new)] = client_patch_manifest(new, parts=[
            {"Name": p["name"], "Bytes": p["bytes"], "SHA256": p["sha256"], "UnpackedBytes": 0}
            for p in (new["parts"][0], replaced)])
        with self.serve():
            latest = updates.resolve_latest(self.co, "new_client", "0.37")
        self.assertFalse(pins.same("new_client", new, latest))
        self.assertEqual(latest["base"], new["base"])

    def test_newer_upstream_named(self) -> None:
        with self.serve():
            self.assertIsNone(updates.newer_upstream(self.co))
        self.responses[self.releases_api] = [{"tag_name": t} for t in ("v0.38b", "v0.38", "v0.37c", "v0.36")]
        with self.serve():
            self.assertEqual(updates.newer_upstream(self.co), "0.38")

    def test_rate_limit_is_named(self) -> None:
        for code in (403, 429):
            self.responses = {self.server_api(): code}
            with self.serve(), self.assertRaises(DaocError) as e:
                updates.resolve_latest(self.co, "server", "0.36")
            self.assertIn("rate limit", e.exception.msg)
            self.assertIn(str(code), e.exception.msg)


class CheckTest(Base):
    def check_all(self):
        before = snapshot(self.root)
        results = []
        with self.serve():
            for argv in (["server", "update", "--check"], ["client", "update", "--check"],
                         ["graphics", "update", "--check"]):
                results.append(run_cli(argv, self.root))
        self.assertEqual(snapshot(self.root), before)
        return results

    def test_up_to_date_and_nothing_written(self) -> None:
        self.select("0.36b")
        self.serve_shipped()
        results = self.check_all()
        ref = self.pin("server", "0.36")["ref"][:12]
        for code, out, err in results:
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(len(out.splitlines()), 1)
            self.assertTrue(out.rstrip().endswith("up to date"), out)
            self.assertIn("Local -", out)
            self.assertIn("built from not installed", out)
        self.assertEqual(results[0][1],
                         f"server@0.36  Shipped {ref}  Local -  built from not installed  "
                         f"latest {ref}  up to date\n")
        self.assertIn("original_client@0.36  Shipped 0.36b", results[1][1])

    def test_check_reports_other_version_without_raising(self) -> None:
        # 0.37 is selected; the server repo's main has moved on to 0.38.
        self.select("0.37b")
        self.serve_shipped("0.37", main=NEW_SHA, marked="0.38")
        server, client, _ = self.check_all()
        self.assertEqual(server[0], 0)
        self.assertIn("server@0.37", server[1])
        self.assertTrue(server[1].rstrip().endswith(
            "server main is now 0.38; this daoc release doesn't support it yet"), server[1])
        self.assertTrue(client[1].rstrip().endswith("up to date"), client[1])

    def test_newer_upstream_is_appended(self) -> None:
        self.select("0.36b")
        self.serve_shipped()
        self.responses[self.releases_api] = [{"tag_name": "v0.38b"}]
        server, client, gfx = self.check_all()
        note = "(0.38 is out upstream; this daoc release doesn't support it yet)"
        self.assertTrue(server[1].rstrip().endswith(note), server[1])
        self.assertTrue(client[1].rstrip().endswith(note), client[1])
        self.assertNotIn(note, gfx[1])

    def test_new_default_client_checks_the_new_client(self) -> None:
        self.select("0.36b", client="new")
        self.serve_shipped()
        _, client, _ = self.check_all()
        self.assertIn("new_client@0.36  Shipped 0.36c", client[1])
        self.assertTrue(client[1].rstrip().endswith("up to date"), client[1])

    def test_update_available_against_the_local_pin(self) -> None:
        self.select("0.36b")
        pins.set_local(self.co, "server", {"upstream": "u", "ref": NEW_SHA}, "0.36")
        self.serve_shipped(main=NEW_SHA, gfx="e" * 40)
        (server, client, gfx) = self.check_all()
        self.assertIn(f"Local {NEW_SHA[:12]}", server[1])
        self.assertTrue(server[1].rstrip().endswith("up to date"), server[1])
        self.assertTrue(client[1].rstrip().endswith("up to date"), client[1])
        self.assertIn(f"latest {'e' * 12}  UPDATE AVAILABLE", gfx[1])


if __name__ == "__main__":
    unittest.main()
