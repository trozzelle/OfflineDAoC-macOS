"""`daoc client install --client new`: the New client, run natively under Godot.

Upstream's 0.36c release is upstream's Godot 4.7.2 .NET client project plus
its converted content (about 34 GB), shipped as independent zips under one
root folder. Only its new-client/godot/ tree is kept: the Windows engine
(tools/godot_net) and launcher (runtime/) are skipped, and daoc runs the
project under the official macOS Godot build pinned in the Version's
`new_client.godot` (MIT).

From 0.37 a release is an update of the 0.36c client: the pin's `base` names
the full release, installed first, and the pin's own parts are the update
(OfflineDAoC-v<x>c-client-patch-partNN.zip). Its patch.json lists every file it
replaces with the hashes it may replace (`From`, or "absent") and the hash it
writes (`Sha256`); each file under new-client/godot/ is checked against both,
so the update only ever lands on the released base.

install, in order (re-runs resume):
  1. Requirements: the Version has a new client; on a fresh install, free disk
     for the unpacked trees, one part and a margin; the .NET 10 runtime
     (server/tools/setup-dotnet.sh, into ~/.dotnet).
  2. Godot: the pinned zip into downloads/godot/, verified, unpacked with ditto
     into dist/godot/Godot_mono.app; skipped when its record names that zip.
  3. Parts, the base's then the update's, one at a time: download, verify
     against the pin, extract the godot/ tree into the staging folder
     (dist/.new-client.new) keeping mtimes (an update's files checked against its
     patch.json, kept in downloads/v<version>/), delete the zip, write
     downloads/v<version>/<part>.done. A done part is not fetched again; a
     staging folder that went missing restarts them all. An installed base
     (0.36c, for 0.37c) is APFS-cloned into staging instead of downloaded.
  4. Record the pin (plus the Game) in the staged install, then swap it in for
     dist/new-client (the previous one moved aside, then removed).
download_only stops after step 3: the staged install is complete, and the next
install only swaps it in. Nothing installed is touched until then.
"""
import json
import os
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import games, pins, proc, release, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, say
from daoc_cli.files import atomic_write, sha256
from daoc_cli.games import Game

KEEP = "new-client/godot/"
MARGIN = 2 * 1024 ** 3
DITTO = "/usr/bin/ditto"
GODOT_RECORD = ".daoc-godot.json"
CP = "/bin/cp"
DONE = ".done"
PATCH_JSON = "patch.json"
ABSENT = "absent"


def _stages(pin: Dict[str, Any]) -> List[Tuple[Dict[str, Any], bool]]:
    """(release, is_update) in install order: the base release, then the pin's update."""
    return [(pin["base"], False), (pin, True)] if pin.get("base") else [(pin, False)]


def needed_bytes(pin: Dict[str, Any]) -> int:
    """Free disk a fresh install needs: the unpacked trees, the largest part, a margin."""
    stages = [r for r, _ in _stages(pin)]
    return (sum(int(r["unpacked_bytes"]) for r in stages)
            + max(int(p["bytes"]) for r in stages for p in r["parts"]) + MARGIN)


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


def _file_sha(path: Path) -> str:
    return sha256(path) if path.is_file() else ABSENT


def read_patch(zip_path: Path, root_folder: str) -> Optional[Dict[str, Any]]:
    """root_folder/patch.json of an update part, or None when this part has none."""
    name = release.plain_name(root_folder, "root_folder") + "/" + PATCH_JSON
    with zipfile.ZipFile(zip_path) as zf:
        if name not in zf.namelist():
            return None
        return json.loads(zf.read(name))


def _godot_files(patch: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The patch's Files under new-client/godot/, by their path below it."""
    return {f["Path"][len(KEEP):]: f for f in patch.get("Files") or [] if f["Path"].startswith(KEEP)}


def apply_update_part(zip_path: Path, root_folder: str, dest: Path, patch: Dict[str, Any]) -> int:
    """Write root_folder/files/new-client/godot/... of an update part over dest
    (the base's godot tree), keeping mtimes; return the files written. Every
    entry must be a file patch.json lists, and the file it replaces must still
    hold one of the hashes the patch replaces (or already the one it writes, on
    a rerun); each written file must hash to the patch's Sha256. The checks on
    the zip's layout run before anything is written."""
    root = release.plain_name(root_folder, "root_folder") + "/"
    keep = root + "files/" + KEEP
    listed = _godot_files(patch)
    base = str(dest.resolve()) + os.sep
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        for info in infos:
            if not info.filename.startswith(root):
                raise DaocError(f"refusing unexpected zip entry {info.filename!r} in {zip_path.name}")
            if info.filename.startswith(keep) and not info.is_dir():
                rel = info.filename[len(keep):]
                target = (dest / rel).resolve()
                if not str(target).startswith(base):
                    raise DaocError(f"zip-slip attempt in {info.filename!r} ({zip_path.name})")
                if rel not in listed:
                    raise DaocError(f"{zip_path.name} carries {rel}, which its patch.json does not list")
        written = 0
        for info in infos:
            if not info.filename.startswith(keep) or info.is_dir():
                continue
            rel = info.filename[len(keep):]
            want, target = listed[rel], dest / rel
            current = _file_sha(target)
            if current == want["Sha256"]:
                continue
            if current not in want["From"]:
                raise DaocError(f"the new client's {rel} is not the file this update replaces "
                                f"({current[:12]}); reinstall the base with daoc client install --client new")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Beside the target, then renamed over it: an interruption leaves the old file or the
            # new one, never a half-written one that neither hash matches.
            tmp = target.with_name(target.name + ".daoc-tmp")
            with zf.open(info) as src, tmp.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            if sha256(tmp) != want["Sha256"]:
                tmp.unlink()
                raise DaocError(f"{rel} from {zip_path.name} failed SHA-256 verification")
            stamp = time.mktime(info.date_time + (0, 0, -1))
            os.utime(tmp, (stamp, stamp))
            os.replace(tmp, target)
            written += 1
    return written


def _clone_tree(src: Path, dest: Path) -> bool:
    """Copy src to dest as APFS clones (no extra disk, mtimes kept); False, leaving
    no dest, when the volume can't clone."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if proc.run([CP, "-c", "-R", "-p", src, dest], check=False).returncode == 0:
        return True
    shutil.rmtree(dest, ignore_errors=True)
    return False


def finish_update(dest: Path, patch: Dict[str, Any]) -> None:
    """After every update part: remove what the patch removes under godot/, and
    check each file it writes is there (each was hash-checked as it was written)."""
    for r in patch.get("Remove") or []:
        if r["Path"].startswith(KEEP):
            target = dest / r["Path"][len(KEEP):]
            current = _file_sha(target)
            if current != ABSENT and current not in r["From"]:
                raise DaocError(f"the new client's {r['Path'][len(KEEP):]} is not the file this update removes")
            target.unlink(missing_ok=True)
    missing = [rel for rel, f in _godot_files(patch).items()
               if not (dest / rel).is_file() or (dest / rel).stat().st_size != f["Bytes"]]
    if missing:
        raise DaocError(f"the update left {len(missing)} new-client file(s) unwritten, e.g. {missing[0]}")


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
    stages = _stages(pin)
    caches = [checkout.downloads / f"v{r['version']}" for r, _ in stages]
    if not staging.exists():
        # Without its staging folder, a done marker (or a kept patch.json) names nothing on disk.
        for cache in caches:
            for marker in [*cache.glob(f"*{DONE}"), cache / PATCH_JSON]:
                marker.unlink(missing_ok=True)
    # An update release on the installed base (0.36c to 0.37c): clone that tree instead of
    # downloading the base again; the update still checks every file it replaces.
    reuse = (not staging.exists() and len(stages) > 1 and checkout.new_client_project.is_dir()
             and pins.same("new_client", record, pin["base"]))
    own = {k: v for k, v in pin.items() if k != "base"}
    _requirements(checkout, game, own if reuse else pin, fresh=not staging.exists())
    install_godot(checkout, pin, fetch_url)
    project = staging / "godot"
    if reuse and _clone_tree(checkout.new_client_project, project):
        say(f"  the installed {pin['base']['version']} client is the update's base: reusing it")
        caches[0].mkdir(parents=True, exist_ok=True)
        for part in pin["base"]["parts"]:
            (caches[0] / (release.plain_name(part["name"], "new client part") + DONE)).touch()
    project.mkdir(parents=True, exist_ok=True)
    parts = [p for (r, _), cache in zip(stages, caches) for p in r["parts"]
             if not (cache / (release.plain_name(p["name"], "new client part") + DONE)).exists()]
    say(f"fetching the new client (about {sum(p['bytes'] for p in parts) / 1024 ** 3:.0f} GB "
        f"in {len(parts)} parts; {sum(r['unpacked_bytes'] for r, _ in stages) / 1024 ** 3:.0f} GB installed)")
    n = 0
    for (rel, is_update), cache in zip(stages, caches):
        cache.mkdir(parents=True, exist_ok=True)
        if is_update:
            say(f"  then the {rel['version']} update of {stages[0][0]['version']}")
        for part in rel["parts"]:
            name = release.plain_name(part["name"], "new client part")
            done = cache / (name + DONE)
            if done.exists():
                continue
            n += 1
            zip_path = cache / name
            say(f"  part {n}/{len(parts)}: {name}")
            _fetch_verified(rel["release_url"] + name, zip_path, part.get("bytes"), part["sha256"], fetch_url)
            if is_update:
                found = read_patch(zip_path, rel["root_folder"])
                if found is not None:
                    atomic_write(cache / PATCH_JSON, json.dumps(found))
                if not (cache / PATCH_JSON).is_file():
                    # Part 1 carries it: forget the done parts so the rerun reads it again.
                    for marker in cache.glob(f"*{DONE}"):
                        marker.unlink()
                    raise DaocError(f"{name}: no patch.json from this update's earlier parts; "
                                    "rerun to fetch them again", 1)
                apply_update_part(zip_path, rel["root_folder"], project,
                                  json.loads((cache / PATCH_JSON).read_text()))
            else:
                extract_filtered(zip_path, rel["root_folder"], project)
            zip_path.unlink()
            done.touch()
        if is_update:
            finish_update(project, json.loads((cache / PATCH_JSON).read_text()))
    pins.record_installed(checkout, "new_client", dict(pin, game=game.name), install=staging)
    if download_only:
        say("new client staged; it replaces the installed one on the next install")
        return
    if checkout.new_client_root.exists():
        checkout.new_client_root.rename(old)
    os.replace(staging, checkout.new_client_root)
    shutil.rmtree(old, ignore_errors=True)
    for cache in caches:
        for marker in [*cache.glob(f"*{DONE}"), cache / PATCH_JSON]:
            marker.unlink(missing_ok=True)
    say(f"new client installed: {checkout.new_client_project}")


def update(checkout: Checkout, game: Game, fetch_url: Optional[release.Downloader] = None) -> None:
    """Move the New client to its release tag's latest assets (a Local pin when they
    differ from the Shipped pin)."""
    if not checkout.new_client_project.is_dir():
        raise DaocError("the new client is not installed: daoc client install --client new", 2)
    latest = updates.resolve_latest(checkout, "new_client", game.version)
    if not pins.same("new_client", pins.effective(checkout, "new_client", game.version), latest):
        pins.set_local(checkout, "new_client", latest, game.version)
    record = pins.installed(checkout, "new_client") or {}
    if pins.same("new_client", record, latest):
        say(f"new client already at {latest['version']}")
        return
    say(f"new client update: {record.get('version', 'unknown')} -> {latest['version']} (new assets)")
    install(checkout, game, fetch_url)
