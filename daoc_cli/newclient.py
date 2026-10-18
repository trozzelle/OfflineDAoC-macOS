"""`daoc client install --client new`: the New client, run natively under Godot.

Upstream's 0.36c release is upstream's Godot 4.7.2 .NET client project plus
its converted content (about 34 GB), shipped as independent zips under one
root folder. Only its new-client/godot/ tree is kept: the Windows engine
(tools/godot_net) and launcher (runtime/) are skipped, and daoc runs the
project under the official macOS Godot build pinned in the Version's
`new_client.godot` (MIT).

install, in order (re-runs resume):
  1. Requirements: the Version has a new client; on a fresh install, free disk
     for the unpacked tree, one part and a margin; the .NET 10 runtime
     (server/tools/setup-dotnet.sh, into ~/.dotnet).
  2. Godot: the pinned zip into downloads/godot/, verified, unpacked with ditto
     into dist/godot/Godot_mono.app; skipped when its record names that zip.
  3. Parts, one at a time: download, verify against the pin, extract the
     godot/ tree into the staging folder (dist/.new-client.new) keeping mtimes,
     delete the zip, write downloads/v<version>/<part>.done. A done part is
     not fetched again; a staging folder that went missing restarts them all.
  4. Record the pin (plus the Game) in the staged install, then swap it in for
     dist/new-client (the previous one moved aside, then removed).
download_only stops after step 3: the staged install is complete, and the next
install only swaps it in. Nothing installed is touched until then.
"""
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from daoc_cli import games, pins, proc, release
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, say
from daoc_cli.files import atomic_write, sha256
from daoc_cli.games import Game

KEEP = "new-client/godot/"
MARGIN = 2 * 1024 ** 3
DITTO = "/usr/bin/ditto"
GODOT_RECORD = ".daoc-godot.json"
DONE = ".done"


def needed_bytes(pin: Dict[str, Any]) -> int:
    """Free disk a fresh install needs: the unpacked tree, the largest part, a margin."""
    return int(pin["unpacked_bytes"]) + max(int(p["bytes"]) for p in pin["parts"]) + MARGIN


def _swap_dirs(checkout: Checkout) -> Tuple[Path, Path]:
    dist = checkout.new_client_root.parent
    return dist / ".new-client.new", dist / ".new-client.old"


def _recover_swap(checkout: Checkout) -> None:
    """Finish or undo a swap that was interrupted between its renames."""
    _, old = _swap_dirs(checkout)
    if old.exists():
        if checkout.new_client_root.exists():
            shutil.rmtree(old)
        else:
            old.rename(checkout.new_client_root)
            say("put back the new client an interrupted install had moved aside")


def extract_filtered(zip_path: Path, root_folder: str, dest: Path) -> int:
    """Extract root_folder/new-client/godot/... of zip_path into dest (that
    prefix dropped), keeping each file's mtime; return the files written. Any
    entry outside root_folder/, or one that would land outside dest, is refused
    before anything is written."""
    root = release.plain_name(root_folder, "root_folder") + "/"
    keep = root + KEEP
    base = str(dest.resolve()) + os.sep
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        for info in infos:
            if not info.filename.startswith(root):
                raise DaocError(f"refusing unexpected zip entry {info.filename!r} in {zip_path.name}")
            if info.filename.startswith(keep):
                target = (dest / info.filename[len(keep):]).resolve()
                if not (str(target) + os.sep).startswith(base) and str(target) != base.rstrip(os.sep):
                    raise DaocError(f"zip-slip attempt in {info.filename!r} ({zip_path.name})")
        written = 0
        for info in infos:
            if not info.filename.startswith(keep) or info.filename == keep:
                continue
            target = dest / info.filename[len(keep):]
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            stamp = time.mktime(info.date_time + (0, 0, -1))
            os.utime(target, (stamp, stamp))
            written += 1
    return written


def ensure_dotnet(checkout: Checkout) -> None:
    """The .NET 10 runtime the client's C# needs, in ~/.dotnet (the server build's installer)."""
    say(".NET 10 (installed into ~/.dotnet if missing)")
    proc.run([checkout.root / "server" / "tools" / "setup-dotnet.sh"], cwd=checkout.root)


def _fetch_verified(url: str, dest: Path, size: Optional[int], want: str,
                    fetch_url: release.Downloader) -> None:
    if dest.is_file() and (size is None or dest.stat().st_size == size) and sha256(dest) == want:
        return
    dest.unlink(missing_ok=True)
    fetch_url(url, dest)
    if sha256(dest) != want:
        dest.unlink()
        raise DaocError(f"{dest.name} failed SHA-256 verification")


def install_godot(checkout: Checkout, pin: Dict[str, Any], fetch_url: release.Downloader) -> None:
    """The pinned macOS Godot .NET build at dist/godot/Godot_mono.app."""
    godot = pin["godot"]
    home = checkout.godot_app.parent
    record = home / GODOT_RECORD
    if checkout.godot_app.is_dir() and record.is_file() and record.read_text().strip() == godot["sha256"]:
        say("Godot already installed")
        return
    cache = checkout.downloads / "godot"
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / release.plain_name(godot["url"].rsplit("/", 1)[-1], "godot url")
    say(f"fetching Godot ({int(godot['bytes']) // 1024 ** 2} MB)")
    _fetch_verified(godot["url"], zip_path, godot.get("bytes"), godot["sha256"], fetch_url)
    unpack = home.parent / ".godot.new"
    shutil.rmtree(unpack, ignore_errors=True)
    proc.run([DITTO, "-x", "-k", zip_path, unpack])
    app = unpack / checkout.godot_app.name
    if not app.is_dir():
        raise DaocError(f"{zip_path.name} holds no {checkout.godot_app.name}")
    shutil.rmtree(home, ignore_errors=True)
    unpack.rename(home)
    atomic_write(record, godot["sha256"] + "\n")


def _requirements(checkout: Checkout, game: Game, pin: Dict[str, Any], fresh: bool) -> None:
    if fresh:
        free = shutil.disk_usage(checkout.root).free
        need = needed_bytes(pin)
        if free < need:
            raise DaocError(f"the new client needs {need / 1024 ** 3:.1f} GB free while it installs; "
                            f"{free / 1024 ** 3:.1f} GB is free", 2)
    ensure_dotnet(checkout)


def install(checkout: Checkout, game: Game, fetch_url: Optional[release.Downloader] = None,
            download_only: bool = False) -> None:
    """Install (or finish installing) the New client for game; see the module doc."""
    if not games.new_client_supported(checkout, game.version):
        raise DaocError(f"the new client exists from 0.36 (game {game.name} has none)", 2)
    fetch_url = fetch_url or release.download
    pin = pins.effective(checkout, "new_client", game.version)
    _recover_swap(checkout)
    staging, old = _swap_dirs(checkout)
    record = pins.installed(checkout, "new_client")
    if (not staging.exists() and checkout.new_client_project.is_dir() and record
            and pins.same("new_client", record, pin)):
        if record.get("game") != game.name:
            pins.record_installed(checkout, "new_client", dict(record, game=game.name))
        say("new client already installed")
        return
    cache = checkout.downloads / f"v{pin['version']}"
    if not staging.exists():
        # Without its staging folder, a done marker names nothing on disk.
        for marker in cache.glob(f"*{DONE}"):
            marker.unlink()
    _requirements(checkout, game, pin, fresh=not staging.exists())
    install_godot(checkout, pin, fetch_url)
    project = staging / "godot"
    project.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    total = len(pin["parts"])
    say(f"fetching the new client (about {sum(p['bytes'] for p in pin['parts']) / 1024 ** 3:.0f} GB "
        f"in {total} parts; {pin['unpacked_bytes'] / 1024 ** 3:.0f} GB installed)")
    for n, part in enumerate(pin["parts"], 1):
        name = release.plain_name(part["name"], "new client part")
        done = cache / (name + DONE)
        if done.exists():
            continue
        zip_path = cache / name
        say(f"  part {n}/{total}: {name}")
        _fetch_verified(pin["release_url"] + name, zip_path, part.get("bytes"), part["sha256"], fetch_url)
        extract_filtered(zip_path, pin["root_folder"], project)
        zip_path.unlink()
        done.touch()
    pins.record_installed(checkout, "new_client", dict(pin, game=game.name), install=staging)
    if download_only:
        say("new client staged; it replaces the installed one on the next install")
        return
    if checkout.new_client_root.exists():
        checkout.new_client_root.rename(old)
    os.replace(staging, checkout.new_client_root)
    shutil.rmtree(old, ignore_errors=True)
    for marker in cache.glob(f"*{DONE}"):
        marker.unlink()
    say(f"new client installed: {checkout.new_client_project}")
