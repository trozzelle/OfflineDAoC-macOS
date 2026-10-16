"""The mtld3d fork build: fetch its pinned bundle and swap it into either Wine.

The bundle (manifest.json "mtld3d") is a tar.xz of the fork's build, cached
in downloads/ and extracted to downloads/mtld3d-<version>/. apply() copies its
files over the Wine tree's own mtld3d files (TARGETS), saving those stock
files first under <wine home>/.daoc-mtld3d/stock/; restore_stock() puts them
back. <wine home>/.daoc-mtld3d.json records the choice (fork or stock), the
fork version and the sha256 of every target's fork and stock bytes; it lives
in the Wine tree, so reinstalling Wine starts over from the new stock files.

Only the Wine tree is written. On arm64 the client install copies Hadron's
lib/hadron/d3d9 files into the prefix afterwards.
"""
import json
import os
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import release
from daoc_cli.errors import DaocError, say
from daoc_cli.files import atomic_write, sha256

# flavour -> [(bundle member, target relative to the Wine home)]
TARGETS: Dict[str, List[Tuple[str, str]]] = {
    "rosetta": [
        ("wine/i386-windows/d3d9.dll", "lib/wine/d3d9/mtld3d/i386-windows/d3d9.dll"),
        ("wine/i386-windows/mtld3d.dll", "lib/wine/d3d9/mtld3d/i386-windows/mtld3d.dll"),
        ("wine/x86_64-windows/d3d9.dll", "lib/wine/d3d9/mtld3d/x86_64-windows/d3d9.dll"),
        ("wine/x86_64-windows/mtld3d.dll", "lib/wine/d3d9/mtld3d/x86_64-windows/mtld3d.dll"),
        ("wine/x86_64-unix/mtld3d.so", "lib/wine/d3d9/mtld3d/x86_64-unix/mtld3d.so"),
    ],
    "arm64": [
        ("native/i386-windows/d3d9.dll", "lib/hadron/d3d9/i386/d3d9.dll"),
        ("wine/i386-windows/mtld3d.dll", "lib/wine/i386-windows/mtld3d.dll"),
        # Hadron ships this marker byte-identical to its builtin mtld3d.dll.
        ("wine/i386-windows/mtld3d.dll", "lib/hadron/d3d9/markers/syswow64/mtld3d.dll"),
        ("wine/aarch64-unix/mtld3d.so", "lib/wine/aarch64-unix/mtld3d.so"),
    ],
}

RECORD = ".daoc-mtld3d.json"
STOCK_DIR = Path(".daoc-mtld3d") / "stock"
CHOICES = ("fork", "stock")
# winebuild --builtin writes this into a PE; the Rosetta Wine loads its
# lib/wine/d3d9/mtld3d DLLs as builtins and must never get a native PE there.
BUILTIN_MARKER = b"Wine builtin DLL"


def _targets(flavour: str) -> List[Tuple[str, str]]:
    try:
        return TARGETS[flavour]
    except KeyError:
        raise DaocError(f"unknown Wine flavour {flavour!r}") from None


def _sha(path: Path) -> Optional[str]:
    """path's sha256; None when there is no file."""
    return sha256(path) if path.is_file() else None


def _read_record(wine_home: Path) -> Dict[str, Any]:
    path = wine_home / RECORD
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {path}: {e}") from None
    if not isinstance(record, dict):
        raise DaocError(f"{path} is not a JSON object")
    return record


def _write_record(wine_home: Path, record: Dict[str, Any]) -> None:
    atomic_write(wine_home / RECORD, json.dumps(record, indent=2, sort_keys=True) + "\n")


def _put(src: Path, dest: Path) -> None:
    """Copy src (bytes and mode) to dest through dest.tmp and os.replace."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(src, tmp)
    shutil.copymode(src, tmp)
    os.replace(tmp, dest)


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def choice(wine_home: Path) -> str:
    """The recorded choice: "fork" (also with no record) or "stock"."""
    value = _read_record(wine_home).get("choice", "fork")
    return value if value in CHOICES else "fork"


def set_choice(wine_home: Path, value: str) -> None:
    if value not in CHOICES:
        raise DaocError(f"mtld3d choice {value!r} is not one of: {', '.join(CHOICES)}", 2)
    record = _read_record(wine_home)
    record["choice"] = value
    _write_record(wine_home, record)


def _check_bundle(bundle: Path, flavour: str) -> Dict[str, str]:
    """{target: fork sha256}, after checking every member is there and, on
    Rosetta, that every DLL carries the builtin marker."""
    fork = {}
    for member, target in _targets(flavour):
        src = bundle / member
        if not src.is_file():
            raise DaocError(f"the mtld3d bundle {bundle} has no {member}")
        if flavour == "rosetta" and target.endswith(".dll") and BUILTIN_MARKER not in src.read_bytes():
            raise DaocError(f"the mtld3d bundle's {member} is not a Wine builtin DLL "
                            "(no winebuild --builtin marker); refusing to install it into the Rosetta Wine")
        fork[target] = sha256(src)
    return fork


def _save_stock(wine_home: Path, flavour: str, fork: Dict[str, str],
                record: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """The stock shas, saving the tree's stock files where the record's are
    missing or out of date (a reinstalled Wine). A target holding fork bytes
    keeps its saved stock copy while that copy still verifies."""
    old_stock = record.get("stock") if isinstance(record.get("stock"), dict) else None
    old_fork = record.get("fork") if isinstance(record.get("fork"), dict) else {}
    stock_dir = wine_home / STOCK_DIR
    stock: Dict[str, Optional[str]] = {}
    for _, target in _targets(flavour):
        current = _sha(wine_home / target)
        is_fork = current is not None and current in (fork[target], old_fork.get(target))
        if is_fork and old_stock is not None and target in old_stock:
            saved = old_stock[target]
            if saved is None or _sha(stock_dir / target) == saved:
                stock[target] = saved
                continue
        stock[target] = current
        copy = stock_dir / target
        if current is None:
            _remove(copy)
        elif _sha(copy) != current:
            _put(wine_home / target, copy)
    return stock


def apply(wine_home: Path, flavour: str, bundle: Path, version: str) -> None:
    """Install the bundle's fork files into the Wine tree, stock saved first.
    A failed run can be repeated: it ends in the fork."""
    fork = _check_bundle(bundle, flavour)
    record = _read_record(wine_home)
    stock = _save_stock(wine_home, flavour, fork, record)
    if stock != record.get("stock"):
        record["stock"] = stock
        record.setdefault("choice", "stock")
        _write_record(wine_home, record)
    for member, target in _targets(flavour):
        if _sha(wine_home / target) != fork[target]:
            _put(bundle / member, wine_home / target)
    record.update(choice="fork", version=version, stock=stock, fork=fork)
    _write_record(wine_home, record)
    say(f"mtld3d {version} installed into {wine_home}")


def restore_stock(wine_home: Path, flavour: str) -> None:
    """Put the saved stock files back (removing targets the stock Wine lacks)."""
    record = _read_record(wine_home)
    stock = record.get("stock")
    if isinstance(stock, dict):
        stock_dir = wine_home / STOCK_DIR
        for _, target in _targets(flavour):
            if target not in stock:
                continue
            want, dest = stock[target], wine_home / target
            if want is None:
                _remove(dest)
                continue
            if _sha(dest) == want:
                continue
            copy = stock_dir / target
            if _sha(copy) != want:
                raise DaocError(f"the saved stock {target} in {stock_dir} is missing or damaged; "
                                "reinstall the Wine to get its stock mtld3d back")
            _put(copy, dest)
    record["choice"] = "stock"
    _write_record(wine_home, record)
    say(f"stock mtld3d restored in {wine_home}")


def state(wine_home: Path, flavour: str) -> str:
    """"fork <version>", "stock" (no record, or every target holds its saved
    stock bytes) or "mixed: <first target that differs from the choice>"."""
    record = _read_record(wine_home)
    stock = record.get("stock")
    if not isinstance(stock, dict):
        return "stock"
    fork = record.get("fork") if isinstance(record.get("fork"), dict) else {}
    current = {t: _sha(wine_home / t) for _, t in _targets(flavour)}
    if fork and all(t in fork and current[t] == fork[t] for t in current):
        return f"fork {record.get('version')}"
    if all(t in stock and current[t] == stock[t] for t in current):
        return "stock"
    want = fork if record.get("choice", "fork") == "fork" else stock
    first = next(t for t in current if t not in want or current[t] != want[t])
    return f"mixed: {first}"


def _members_ok(directory: Path, members: Dict[str, str]) -> bool:
    return all(_sha(directory / name) == want for name, want in members.items())


def _extract(archive: Path, dest: Path) -> None:
    """Extract the tar.xz into dest through dest.tmp; only plain files and
    directories with relative paths inside dest are accepted."""
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        with tarfile.open(archive, "r:xz") as tf:
            for info in tf.getmembers():
                name = PurePosixPath(info.name)
                if name.is_absolute() or ".." in name.parts:
                    raise DaocError(f"refusing unsafe entry {info.name!r} in {archive.name}")
                if info.isdir():
                    (tmp / name).mkdir(parents=True, exist_ok=True)
                    continue
                if not info.isfile():
                    raise DaocError(f"refusing non-file entry {info.name!r} in {archive.name}")
                out = tmp / name
                out.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(info)
                assert src is not None  # isfile()
                with src, out.open("wb") as f:
                    shutil.copyfileobj(src, f, 1 << 20)
                out.chmod(info.mode & 0o755 | 0o644)
    except (tarfile.TarError, OSError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise DaocError(f"cannot extract {archive}: {e}") from None
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(tmp, dest)


def fetch_bundle(checkout: Any, fetch_url: release.Downloader = release.download) -> Path:
    """downloads/mtld3d-<version>/: the pinned bundle, downloaded (or reused
    from downloads/<asset>), sha256-verified and extracted. An extraction
    whose files match the pin's members (when it lists them) is reused."""
    try:
        pin = checkout.manifest["mtld3d"]
        url, asset, want, version = pin["url"], pin["asset"], pin["sha256"], pin["version"]
    except (KeyError, TypeError) as e:
        raise DaocError(f"manifest.json has no complete mtld3d pin (missing {e})") from None
    downloads = Path(checkout.downloads)
    archive = downloads / release.plain_name(asset, "mtld3d asset")
    dest = downloads / release.plain_name(f"mtld3d-{version}", "mtld3d version")
    members = pin.get("members")
    if dest.is_dir() and (not isinstance(members, dict) or _members_ok(dest, members)):
        return dest
    downloads.mkdir(parents=True, exist_ok=True)
    if _sha(archive) != want:
        _remove(archive)
        fetch_url(url, archive)
        actual = sha256(archive)
        if actual != want:
            archive.unlink()
            raise DaocError(f"{asset} failed sha256 verification\n  expected {want}\n  actual   {actual}")
    _extract(archive, dest)
    if isinstance(members, dict) and not _members_ok(dest, members):
        shutil.rmtree(dest)
        raise DaocError(f"{asset} does not hold the pinned mtld3d members")
    say(f"mtld3d {version} bundle ready in {dest}")
    return dest
