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
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from daoc_cli.errors import DaocError, say
from daoc_cli.files import sha256, sha256_of

Downloader = Callable[[str, Path], None]
USER_AGENT = "daoc-macos-installer/1.0"


def download(url: str, dest: Path) -> None:
    """GET url into dest through dest.part, so an interrupted download is
    never mistaken for a cached file."""
    say(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
    return sha256(path) == sha


def _changed(what: str) -> DaocError:
    return DaocError(f"{what}; upstream changed the release, so the client pin has to be "
                     "moved deliberately")


def plain_name(name: Any, what: str) -> str:
    """name, refused unless it is one plain path component: release manifests
    come from the network, and their names are joined onto local directories."""
    if not isinstance(name, str) or name in ("", "..") or Path(name).name != name:
        raise DaocError(f"{what} {name!r} is not a plain file name")
    return name


def _cache_path(cache_dir: Path, name: str, what: str) -> Path:
    """cache_dir/name, refused unless it stays directly inside cache_dir (a
    symlink there that leads elsewhere is refused too)."""
    path = cache_dir / plain_name(name, what)
    if path.resolve().parent != cache_dir.resolve():
        raise DaocError(f"{what} {name!r} resolves outside {cache_dir}")
    return path


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


def download_release(pin: Dict[str, Any], cache_dir: Path,
                     *, fetch_url: Downloader = download) -> Path:
    """Download (or reuse) and verify the pinned release in cache_dir; returns
    the verified, joined archive. Nothing is extracted."""
    release_url = pin["release_url"]  # a URL: must stay a string; a Path would mangle '//'
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Release manifest, cross-checked against the pin.
    manifest_name = pin.get("manifest_asset", "download-manifest.json")
    manifest_path = _cache_path(cache_dir, manifest_name, "manifest_asset")
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
        dest = _cache_path(cache_dir, name, "release part")
        if _verified(dest, want.get("bytes"), sha):
            say(f"  cached {name} (verified)")
            continue
        if dest.exists():
            dest.unlink()
        fetch_url(release_url + name, dest)
        if sha256(dest) != sha:
            raise DaocError(f"{name} failed SHA-256 verification")
        say(f"  verified {name}")

    # 3. Join + whole-archive verification.
    archive = _cache_path(cache_dir, f"OfflineDAoC-v{pin['version']}.zip", "archive")
    if not _verified(archive, pin.get("archive_bytes"), pin["archive_sha256"]):
        say("  joining parts")
        with archive.open("wb") as out:
            for want in pin["parts"]:
                with _cache_path(cache_dir, want["name"], "release part").open("rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
        if sha256(archive) != pin["archive_sha256"]:
            raise DaocError("joined archive failed SHA-256 verification")
    say(f"  archive verified ({pin['archive_sha256'][:16]}…)")
    return archive


def member_sha256(archive: Path, name: str) -> str:
    """sha256 of one file inside the archive, read without extracting anything."""
    with zipfile.ZipFile(archive) as zf:
        try:
            src = zf.open(name)
        except KeyError:
            raise DaocError(f"{archive.name} has no {name}") from None
        with src:
            return sha256_of(src)


def extract(archive: Path, root_folder: str, dest_dir: Path) -> Path:
    """Extract a verified archive into dest_dir with zip-slip validation;
    returns dest_dir/<root_folder>. An existing destination is refused."""
    target = dest_dir / plain_name(root_folder, "root_folder")
    if target.exists():
        raise DaocError(f"destination {target} already exists")
    dest_dir.mkdir(parents=True, exist_ok=True)
    say("  extracting (this takes a few minutes)")
    root_prefix = f"{root_folder}/"
    base = str(dest_dir.resolve()) + "/"
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name.startswith(root_prefix):
                raise DaocError(f"refusing unexpected zip entry {name!r}")
            if not str((dest_dir / name).resolve()).startswith(base):
                raise DaocError(f"zip-slip attempt in {name!r}")
        zf.extractall(dest_dir)
    say(f"  extracted to {target}")
    return target
