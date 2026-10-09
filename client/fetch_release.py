#!/usr/bin/env python3
"""Fetch and verify an OfflineDAoC release, then extract it.

Mirrors upstream's Get-OfflineDAoC.ps1 scheme (manifest -> per-part SHA-256 ->
whole-archive SHA-256 -> zip-slip-checked extraction), using the pinned part
hashes from manifest.json as a second, local line of defense.

Usage: fetch_release.py <release_asset_url> <cache_dir> <root_folder> <dest_dir>

The release's own download-manifest.json is downloaded from <release_asset_url>
and cross-checked against the pins in manifest.json; a mismatch of any pin
against the release manifest is fatal (upstream changed something — update the
manifest deliberately, via update.sh).
"""
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "daoc-macos-installer/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req) as r, tmp.open("wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    release_url, cache_dir, root_folder, dest_dir = (Path(a) for a in sys.argv[1:])
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    pins = json.loads((REPO / "manifest.json").read_text())["client"]
    version = pins["version"]

    # 1. Release manifest — cross-check against our pins.
    manifest_path = cache_dir / "download-manifest.json"
    if not manifest_path.exists():
        download(f"{release_url}download-manifest.json", manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("Version") != version:
        print(f"fetch_release: release manifest version {manifest.get('Version')!r} "
              f"!= pinned {version!r} — upstream moved; run update.sh", file=sys.stderr)
        return 1
    if manifest.get("ArchiveSHA256") != pins["archive_sha256"]:
        print("fetch_release: release ArchiveSHA256 differs from the pinned value — "
              "upstream republished; verify and update manifest.json (update.sh)",
              file=sys.stderr)
        return 1

    # 2. Parts: download missing ones, verify each against BOTH the release
    #    manifest and our pin.
    parts = manifest["Parts"]
    if len(parts) != len(pins["parts"]):
        print("fetch_release: part list changed upstream — update manifest.json "
              "(update.sh)", file=sys.stderr)
        return 1
    for part, pin in zip(parts, pins["parts"]):
        if part["Name"] != pin["name"] or part["SHA256"] != pin["sha256"]:
            print(f"fetch_release: part {part['Name']} differs from the pinned "
                  f"{pin['name']} — update manifest.json (update.sh)", file=sys.stderr)
            return 1
        dest = cache_dir / part["Name"]
        if dest.exists() and sha256_file(dest) == part["SHA256"]:
            print(f"  cached {part['Name']} (verified)")
            continue
        if dest.exists():
            dest.unlink()
        download(f"{release_url}{part['Name']}", dest)
        if sha256_file(dest) != part["SHA256"]:
            print(f"fetch_release: {part['Name']} failed SHA-256 verification",
                  file=sys.stderr)
            return 1
        print(f"  verified {part['Name']}")

    # 3. Join + whole-archive verification.
    archive = cache_dir / f"OfflineDAoC-v{version}.zip"
    if not archive.exists() or sha256_file(archive) != manifest["ArchiveSHA256"]:
        print("  joining parts")
        with archive.open("wb") as out:
            for part in parts:
                with (cache_dir / part["Name"]).open("rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
        if sha256_file(archive) != manifest["ArchiveSHA256"]:
            print("fetch_release: joined archive failed SHA-256 verification",
                  file=sys.stderr)
            return 1
    print(f"  archive verified ({manifest['ArchiveSHA256'][:16]}…)")

    # 4. Extract with zip-slip validation; refuse an existing destination.
    target = dest_dir / root_folder
    if (dest_dir / root_folder).exists() or target.exists():
        print(f"fetch_release: destination {target} already exists", file=sys.stderr)
        return 1
    print("  extracting (this takes a few minutes)")
    root_prefix = f"{manifest['RootFolder']}/"
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(root_prefix):
                print(f"fetch_release: refusing unexpected zip entry {name!r}",
                      file=sys.stderr)
                return 1
            resolved = (dest_dir / name).resolve()
            if not str(resolved).startswith(str(dest_dir.resolve()) + "/"):
                print(f"fetch_release: zip-slip attempt in {name!r}", file=sys.stderr)
                return 1
        zf.extractall(dest_dir)
    print(f"  extracted to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())