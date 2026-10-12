"""updates: resolve_latest against canned GitHub JSON, and `update --check` changes nothing."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import pins, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

API = "https://api.github.com/repos/"
NEW_SHA = "1234567890ab" + "c" * 28


def release_manifest(version, sha="a" * 64):
    return {
        "Version": version,
        "RootFolder": f"OfflineDAoC-v{version}",
        "ArchiveSHA256": sha,
        "ArchiveBytes": 30,
        "Parts": [
            {"Name": f"OfflineDAoC-v{version}.zip.001", "Bytes": 20, "SHA256": "b" * 64},
            {"Name": f"OfflineDAoC-v{version}.zip.002", "Bytes": 10, "SHA256": "d" * 64},
        ],
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
        self.server_api = API + m["server"]["upstream"][len("https://github.com/"):] + "/commits/main"
        self.gfx_api = API + m["graphics"]["repo"][len("https://github.com/"):] + "/commits/main"
        self.release_api = API + "shadowofze/OfflineDAoC/releases/latest"
        self.responses = {}
        self.seen = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def asset(self, tag):
        return f"https://github.com/shadowofze/OfflineDAoC/releases/download/{tag}/download-manifest.json"

    def urlopen(self, req, timeout=None):
        url = req.full_url
        self.seen.append(url)
        answer = self.responses[url]
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "Forbidden", {}, None)
        return io.BytesIO(json.dumps(answer).encode())

    def serve(self):
        return mock.patch.object(updates.urllib.request, "urlopen", self.urlopen)

    def serve_shipped(self, server=None, gfx=None):
        """Latest == Shipped for every group unless a sha is given."""
        m = self.co.manifest
        client = m["client"]
        tag = "v" + client["version"]
        self.responses.update({
            self.server_api: {"sha": server or m["server"]["ref"]},
            self.gfx_api: {"sha": gfx or m["graphics"]["ref"]},
            self.release_api: {"tag_name": tag},
            self.asset(tag): {
                "Version": client["version"],
                "RootFolder": client["root_folder"],
                "ArchiveSHA256": client["archive_sha256"],
                "ArchiveBytes": client["archive_bytes"],
                "Parts": [{"Name": p["name"], "Bytes": p["bytes"], "SHA256": p["sha256"]}
                          for p in client["parts"]],
            },
        })


class ResolveLatestTest(Base):
    def test_server_and_graphics_main_sha(self) -> None:
        self.responses = {self.server_api: {"sha": NEW_SHA}, self.gfx_api: {"sha": "f" * 40}}
        with self.serve():
            server = updates.resolve_latest(self.co, "server")
            gfx = updates.resolve_latest(self.co, "graphics")
        self.assertEqual(server, {"upstream": self.co.manifest["server"]["upstream"], "ref": NEW_SHA})
        self.assertEqual(gfx, {"repo": self.co.manifest["graphics"]["repo"], "ref": "f" * 40})

    def test_client_unchanged_version_is_the_shipped_entry(self) -> None:
        self.serve_shipped()
        with self.serve():
            latest = updates.resolve_latest(self.co, "client")
        self.assertEqual(latest, pins.shipped(self.co, "client"))
        self.assertEqual(list(latest), [k for k in self.co.manifest["client"] if k != "note"])

    def test_client_new_release(self) -> None:
        self.responses = {self.release_api: {"tag_name": "v0.36"},
                          self.asset("v0.36"): release_manifest("0.36")}
        with self.serve():
            latest = updates.resolve_latest(self.co, "client")
        self.assertEqual(latest, {
            "release_url": "https://github.com/shadowofze/OfflineDAoC/releases/download/v0.36/",
            "version": "0.36",
            "manifest_asset": "download-manifest.json",
            "root_folder": "OfflineDAoC-v0.36",
            "archive_sha256": "a" * 64,
            "archive_bytes": 30,
            "parts": [
                {"name": "OfflineDAoC-v0.36.zip.001", "bytes": 20, "sha256": "b" * 64},
                {"name": "OfflineDAoC-v0.36.zip.002", "bytes": 10, "sha256": "d" * 64},
            ],
            "game_dll_sha256": None,
        })

    def test_client_manifest_version_mismatch(self) -> None:
        self.responses = {self.release_api: {"tag_name": "v0.36"},
                          self.asset("v0.36"): release_manifest("0.35b")}
        with self.serve(), self.assertRaises(DaocError) as e:
            updates.resolve_latest(self.co, "client")
        self.assertIn("0.35b", e.exception.msg)

    def test_rate_limit_is_named(self) -> None:
        for code in (403, 429):
            self.responses = {self.server_api: code}
            with self.serve(), self.assertRaises(DaocError) as e:
                updates.resolve_latest(self.co, "server")
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
        self.serve_shipped()
        results = self.check_all()
        ref = self.co.manifest["server"]["ref"][:12]
        for code, out, err in results:
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(len(out.splitlines()), 1)
            self.assertTrue(out.rstrip().endswith("up to date"), out)
            self.assertIn("Local -", out)
            self.assertIn("built from not installed", out)
        self.assertEqual(results[0][1],
                         f"server    Shipped {ref}  Local -  built from not installed  "
                         f"latest {ref}  up to date\n")
        self.assertIn("Shipped 0.35b", results[1][1])

    def test_update_available_against_the_local_pin(self) -> None:
        pins.set_local(self.co, "server", {"upstream": "u", "ref": NEW_SHA})
        self.serve_shipped(server=NEW_SHA, gfx="e" * 40)
        (server, client, gfx) = self.check_all()
        self.assertIn(f"Local {NEW_SHA[:12]}", server[1])
        self.assertTrue(server[1].rstrip().endswith("up to date"), server[1])
        self.assertTrue(client[1].rstrip().endswith("up to date"), client[1])
        self.assertIn(f"latest {'e' * 12}  UPDATE AVAILABLE", gfx[1])

    def test_update_without_check_is_refused_for_client_and_graphics(self) -> None:
        for argv in (["client", "update"], ["graphics", "update"]):
            code, _, err = run_cli(argv, self.root)
            self.assertEqual(code, 2)
            self.assertIn("not available yet", err)


if __name__ == "__main__":
    unittest.main()
