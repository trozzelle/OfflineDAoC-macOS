"""Fetch and verify an OfflineDAoC release, then extract it.

Mirrors upstream's Get-OfflineDAoC.ps1 scheme (release manifest -> per-part
SHA-256 -> whole-archive SHA-256 -> zip-slip-checked extraction), using the
part hashes of the effective client pin as a second, local line of defense.

The release's own download-manifest.json is downloaded from the pin's
release_url and cross-checked against the pin; a mismatch of any pinned field
against the release manifest is fatal: upstream changed something, and the pin
has to be moved deliberately. Parts, the release manifest and the joined
archive are cached in downloads/v<version>/.
"""
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from daoc_cli import pins
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

Downloader = Callable[[str, Path], None]


def _say(msg: str) -> None:
    print(f"daoc: {msg}", file=sys.stderr, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    """GET url into dest through dest.part, so an interrupted download is
    never mistaken for a cached file."""
    _say(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "daoc-macos-installer/1.0"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except OSError as e:
        raise DaocError(f"download of {url} failed: {e}") from None
    tmp.replace(dest)


def _verified(path: Path, size: Optional[int], sha: str) -> bool:
    """path exists with the expected sha256; a pinned size that differs skips
    hashing a multi-GB file."""
    if not path.is_file():
        return False
    if size is not None and path.stat().st_size != size:
        return False
    return sha256_file(path) == sha


def _changed(what: str) -> DaocError:
    return DaocError(f"{what}; upstream changed the release, so the client pin has to be "
                     "moved deliberately")


def _verify_release_manifest(manifest: Dict[str, Any], pin: Dict[str, Any]) -> None:
    if manifest.get("Version") != pin["version"]:
        raise _changed(f"release manifest version {manifest.get('Version')!r} "
                       f"!= pinned {pin['version']!r}")
    if manifest.get("ArchiveSHA256") != pin["archive_sha256"]:
        raise _changed("release ArchiveSHA256 differs from the pinned value")
    if manifest.get("RootFolder") != pin["root_folder"]:
        raise _changed(f"release RootFolder {manifest.get('RootFolder')!r} "
                       f"!= pinned {pin['root_folder']!r}")
    parts = manifest.get("Parts") or []
    if len(parts) != len(pin["parts"]):
        raise _changed("the release's part list differs from the pinned one")
    for part, want in zip(parts, pin["parts"]):
        if part.get("Name") != want["name"] or part.get("SHA256") != want["sha256"]:
            raise _changed(f"release part {part.get('Name')} differs from the pinned "
                           f"{want['name']}")


def fetch(pin: Dict[str, Any], cache_dir: Path, dest_dir: Path,
          *, fetch_url: Downloader = download) -> Path:
    """Download (or reuse) and verify the pinned release in cache_dir, then
    extract it into dest_dir; returns dest_dir/<root_folder>.

    fetch_url(url, dest) downloads one file (tests pass their own).
    """
    release_url = pin["release_url"]  # a URL: must stay a string; a Path would mangle '//'
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Release manifest, cross-checked against the pin.
    manifest_name = pin.get("manifest_asset", "download-manifest.json")
    manifest_path = cache_dir / manifest_name
    if not manifest_path.exists():
        fetch_url(release_url + manifest_name, manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {manifest_path}: {e}") from None
    _verify_release_manifest(manifest, pin)

    # 2. Parts: download missing ones, verify each against the pin (which the
    #    release manifest was just checked to match).
    for want in pin["parts"]:
        name, sha = want["name"], want["sha256"]
        dest = cache_dir / name
        if _verified(dest, want.get("bytes"), sha):
            _say(f"  cached {name} (verified)")
            continue
        if dest.exists():
            dest.unlink()
        fetch_url(release_url + name, dest)
        if sha256_file(dest) != sha:
            raise DaocError(f"{name} failed SHA-256 verification")
        _say(f"  verified {name}")

    # 3. Join + whole-archive verification.
    archive = cache_dir / f"OfflineDAoC-v{pin['version']}.zip"
    if not _verified(archive, pin.get("archive_bytes"), pin["archive_sha256"]):
        _say("  joining parts")
        with archive.open("wb") as out:
            for want in pin["parts"]:
                with (cache_dir / want["name"]).open("rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
        if sha256_file(archive) != pin["archive_sha256"]:
            raise DaocError("joined archive failed SHA-256 verification")
    _say(f"  archive verified ({pin['archive_sha256'][:16]}…)")

    # 4. Extract with zip-slip validation; refuse an existing destination.
    target = dest_dir / pin["root_folder"]
    if target.exists():
        raise DaocError(f"destination {target} already exists")
    _say("  extracting (this takes a few minutes)")
    root_prefix = f"{pin['root_folder']}/"
    base = str(dest_dir.resolve()) + "/"
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(root_prefix):
                raise DaocError(f"refusing unexpected zip entry {name!r}")
            if not str((dest_dir / name).resolve()).startswith(base):
                raise DaocError(f"zip-slip attempt in {name!r}")
        zf.extractall(dest_dir)
    _say(f"  extracted to {target}")
    return target


def install(checkout: Checkout, *, fetch_url: Downloader = download) -> None:
    """Fetch the effective client pin's release into checkout.client_root."""
    pin = pins.effective(checkout, "client")
    dist = checkout.client_root.parent
    extracted = fetch(pin, checkout.downloads / f"v{pin['version']}", dist, fetch_url=fetch_url)
    # The archive's root is <root_folder>/; the install lives under a fixed name.
    extracted.rename(checkout.client_root)
