"""Shipped pins, Local pins, and which one applies.

A Shipped pin is an entry of the tracked manifest.json, minus its `note`. The
server, original_client and new_client pins (VERSIONED) live under each game
Version (`versions.<version>.<group>`); the graphics pin is top level. A user
update records a Local pin instead of editing the manifest, so an updated
Checkout stays clean and checking out the next release never conflicts on it.
Local pins live in the gitignored <checkout>/.daoc/pins.json, one entry per
(group, version):

    {"group": "server", "version": "0.36", "pin": {...}, "replaces": {...}, "at": "2026-10-11T12:00:00Z"}

`replaces` is the Shipped pin the Local pin was made against. Once a release
changes that Shipped pin, the Local pin lapses: it is dropped with a one-line
notice and the new Shipped pin applies. Only ship() writes the manifest, for a
maintainer to commit.

The Server, Original client and New client installs record the pin they were
built from in their own folder (INSTALLED), so whether an install is up to
date is read from the install, never inferred from the pin (built_from).
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import games, proc
from daoc_cli.checkout import Checkout
from daoc_cli.files import atomic_write, sha256
from daoc_cli.errors import DaocError, say

GROUPS = ("server", "original_client", "new_client", "graphics")
VERSIONED = ("server", "original_client", "new_client")

# The field that names a pin: two pins with the same value are the same
# upstream state. In messages, refs are shortened to 12 hex chars.
_KEY = {"server": "ref", "original_client": "version", "new_client": "version", "graphics": "ref"}

NOT_INSTALLED = "not installed"
UNKNOWN = "unknown"

# The one client the tooling installed before the install record existed.
# Every Proven release then shared its game.dll, so the hash names no other version.
LEGACY_CLIENT = {
    "version": "0.35b",
    "edition": "sluaghbinder",
    "game_dll_sha256": "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b",
}

STORE = "pins.json"
# In the install folders: the pin the install was built from.
INSTALLED = ".daoc-pin.json"
LEGACY_NOTICE = "Local client pin from before game versions dropped"


def _check_group(group: str) -> None:
    if group not in GROUPS:
        raise DaocError(f"no pin group {group!r} (expected one of: {', '.join(GROUPS)})")


def _version_of(group: str, version: Optional[str]) -> Optional[str]:
    """The version a group's pin is read for: required for VERSIONED, None for graphics."""
    _check_group(group)
    if group not in VERSIONED:
        return None
    if not version:
        raise DaocError(f"the {group} pin needs a game version")
    return version


def label(group: str, version: Optional[str]) -> str:
    """`server@0.36`, or `graphics`: how messages and ship() name a pin."""
    return f"{group}@{version}" if group in VERSIONED and version else group


def short(group: str, fields: Optional[Dict[str, Any]]) -> str:
    """The pin's name for messages: 12 chars of `ref`, or the client `version`."""
    _check_group(group)
    value = (fields or {}).get(_KEY[group])
    if value is None:
        return UNKNOWN
    value = str(value)
    return value[:12] if _KEY[group] == "ref" else value


# Fields that also tell two client pins of one tag apart: upstream can replace a
# tag's assets. Compared only when both pins carry them (an old install record may not).
_IDENTITY = {"original_client": ("archive_sha256",), "new_client": ("parts",)}


def same(group: str, a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    """Whether two pins name the same upstream state (ref, or client version and archive)."""
    if not (a and b) or a.get(_KEY[group]) != b.get(_KEY[group]):
        return False
    return all(a[f] == b[f] for f in _IDENTITY.get(group, ()) if f in a and f in b)


def shipped(checkout: Checkout, group: str, version: Optional[str] = None) -> Dict[str, Any]:
    """The pin fields from manifest.json (the entry without `note`)."""
    version = _version_of(group, version)
    if version is None:
        entry = checkout.manifest.get(group)
    else:
        entry = games.entry(checkout, version).get(group)
        if entry is None and group == "new_client":
            raise DaocError(f"game version {version} has no new client", 2)
    if not isinstance(entry, dict):
        raise DaocError(f"manifest.json has no {label(group, version)} entry")
    return {k: v for k, v in entry.items() if k != "note"}


def _store_path(checkout: Checkout) -> Path:
    return checkout.state / STORE


def _legacy(entry: Any) -> bool:
    """An entry written before pins were per game version."""
    return isinstance(entry, dict) and (
        entry.get("group") == "client"
        or (entry.get("group") in VERSIONED and not entry.get("version")))


def _load(checkout: Checkout) -> List[Dict[str, Any]]:
    path = _store_path(checkout)
    try:
        with path.open(encoding="utf-8") as f:
            entries = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {path}: {e}") from None
    if isinstance(entries, list) and any(_legacy(e) for e in entries):
        entries = [e for e in entries if not _legacy(e)]
        _save(checkout, entries)
        say(LEGACY_NOTICE)
    if not isinstance(entries, list) or not all(
        isinstance(e, dict) and e.get("group") in GROUPS
        and isinstance(e.get("pin"), dict) and isinstance(e.get("replaces"), dict)
        for e in entries
    ):
        raise DaocError(f"{path} is not a list of Local pin entries; remove it to drop all Local pins")
    return entries


def _save(checkout: Checkout, entries: List[Dict[str, Any]]) -> None:
    """Write the store, or delete it when no entry is left."""
    path = _store_path(checkout)
    if not entries:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    atomic_write(path, json.dumps(entries, indent=2) + "\n")


def _entry(entries: List[Dict[str, Any]], group: str, version: Optional[str]) -> Optional[Dict[str, Any]]:
    for entry in entries:
        if entry["group"] == group and entry.get("version") == version:
            return entry
    return None


def local(checkout: Checkout, group: str, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The Local pin while it still applies, else None.

    Side-effect free for a current store: a lapsed entry is reported as None but
    left in the store; effective() is what drops it and prints the notice.
    """
    version = _version_of(group, version)
    entry = _entry(_load(checkout), group, version)
    if entry is None or entry["replaces"] != shipped(checkout, group, version):
        return None
    return dict(entry["pin"])


def effective(checkout: Checkout, group: str, version: Optional[str] = None) -> Dict[str, Any]:
    """The pin that applies: the Local pin while its `replaces` still equals the
    Shipped pin, else the Shipped pin. A lapsed Local pin is dropped from the
    store with a one-line notice on stderr."""
    version = _version_of(group, version)
    current = shipped(checkout, group, version)
    entries = _load(checkout)
    entry = _entry(entries, group, version)
    if entry is None:
        return current
    if entry["replaces"] == current:
        return dict(entry["pin"])
    _save(checkout, [e for e in entries if e is not entry])
    say(f"Local {label(group, version)} pin {short(group, entry['pin'])} lapsed; "
        f"Shipped pin {short(group, current)} applies")
    return current


def set_local(checkout: Checkout, group: str, fields: Dict[str, Any],
              version: Optional[str] = None) -> None:
    """Record fields as the Local pin, made against the current Shipped pin."""
    version = _version_of(group, version)
    if not isinstance(fields, dict) or not fields:
        raise DaocError(f"a Local {label(group, version)} pin needs its pin fields")
    entries = [e for e in _load(checkout)
               if not (e["group"] == group and e.get("version") == version)]
    entry: Dict[str, Any] = {"group": group}
    if version is not None:
        entry["version"] = version
    entry.update({
        "pin": {k: v for k, v in fields.items() if k != "note"},
        "replaces": shipped(checkout, group, version),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    entries.append(entry)
    entries.sort(key=lambda e: (GROUPS.index(e["group"]), e.get("version") or ""))
    _save(checkout, entries)


def _install_dir(checkout: Checkout, group: str) -> Path:
    if group == "server":
        return checkout.server_dir
    if group == "original_client":
        return checkout.client_root
    if group == "new_client":
        return checkout.new_client_root
    raise DaocError(f"the {group} install records no pin")


def installed(checkout: Checkout, group: str) -> Optional[Dict[str, Any]]:
    """The pin the group's install records it was built from; None when it
    records none (no install, an install made before the record, or a build
    that did not finish)."""
    try:
        fields = json.loads((_install_dir(checkout, group) / INSTALLED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return fields if isinstance(fields, dict) else None


def record_installed(checkout: Checkout, group: str, fields: Dict[str, Any],
                     install: Optional[Path] = None) -> None:
    """Record fields as the pin the group's install was built from; install
    names another folder to record into (a staged install before its swap)."""
    path = (_install_dir(checkout, group) if install is None else install) / INSTALLED
    atomic_write(path, json.dumps({k: v for k, v in fields.items() if k != "note"},
                                  indent=2) + "\n")


def forget_installed(checkout: Checkout, group: str) -> None:
    """Drop the install's record before a rebuild changes the install."""
    try:
        (_install_dir(checkout, group) / INSTALLED).unlink()
    except FileNotFoundError:
        pass


def built_from(checkout: Checkout, group: str, pin: Dict[str, Any]) -> Tuple[str, Optional[bool]]:
    """(label, whether the install was built from pin), read from the install
    itself and offline; matches is None when unknown.

      - server, new_client: the pin the install records (INSTALLED) once it
        is complete. An install without that record names no upstream state,
        so built-from is unknown.
      - original_client: the pin recorded in the install (INSTALLED). An
        install made before that record came from the old tooling, which only
        installed LEGACY_CLIENT: its pristine game.dll (game.dll.orig once
        patched) is matched against that pin alone, and the record is written
        once it matches.
      - graphics: the HEAD commit of the upstream/graphics clone.
    """
    _check_group(group)
    if group == "graphics":
        if not checkout.graphics_src.is_dir():
            return NOT_INSTALLED, None
        head = proc.git_out(checkout.graphics_src, "rev-parse", "HEAD")
        if not head:
            return UNKNOWN, None
        return head[:12], head == pin.get("ref")
    folder = checkout.app_dir if group == "original_client" else _install_dir(checkout, group)
    if not folder.is_dir():
        return NOT_INSTALLED, None
    record = installed(checkout, group)
    if record is None and group == "original_client":
        dll = checkout.app_dir / "game.dll.orig"
        if not dll.is_file():
            dll = checkout.app_dir / "game.dll"
        try:
            sha = sha256(dll)
        except OSError:
            return UNKNOWN, None
        if sha != LEGACY_CLIENT["game_dll_sha256"]:
            return f"game.dll {sha[:12]}", False
        record_installed(checkout, group, LEGACY_CLIENT)
        record = LEGACY_CLIENT
    if record is None:
        return UNKNOWN, None
    return short(group, record), same(group, record, pin)


def _merge(entry: Dict[str, Any], pin: Dict[str, Any]) -> Dict[str, Any]:
    """entry with its pin fields replaced by pin: existing keys keep their
    order and `note` its place; new fields go just before `note`."""
    merged: Dict[str, Any] = {}
    for key, value in entry.items():
        if key == "note":
            for new_key, new_value in pin.items():
                if new_key not in entry:
                    merged[new_key] = new_value
            merged[key] = value
        elif key in pin:
            merged[key] = pin[key]
    for key, value in pin.items():
        merged.setdefault(key, value)
    return merged


def _dump(value: Any, indent: int = 0, inline: bool = False) -> str:
    """JSON in manifest.json's layout: 2-space indents, and objects inside
    arrays on one line as `{ "k": v, ... }`."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        if inline:
            return "{ " + ", ".join(
                f"{json.dumps(k, ensure_ascii=False)}: {_dump(v, inline=True)}"
                for k, v in value.items()) + " }"
        pad = " " * (indent + 2)
        body = ",\n".join(
            f"{pad}{json.dumps(k, ensure_ascii=False)}: {_dump(v, indent + 2)}"
            for k, v in value.items())
        return "{\n" + body + "\n" + " " * indent + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if inline:
            return "[" + ", ".join(_dump(v, inline=True) for v in value) + "]"
        pad = " " * (indent + 2)
        body = ",\n".join(f"{pad}{_dump(v, indent + 2, inline=True)}" for v in value)
        return "[\n" + body + "\n" + " " * indent + "]"
    return json.dumps(value, ensure_ascii=False)


def ship(checkout: Checkout) -> List[str]:
    """Write the effective pins into manifest.json, clear the Local pins, and
    return the pins whose manifest entry changed (`server@0.36`, `graphics`).

    Every other manifest key, each entry's `note` and the key order are kept.
    """
    path = checkout.root / "manifest.json"
    try:
        text = path.read_text(encoding="utf-8")
        manifest = json.loads(text)
    except FileNotFoundError:
        raise DaocError(f"{path} is missing") from None
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {path}: {e}") from None
    written = []
    targets: List[Tuple[str, Optional[str], Dict[str, Any]]] = []
    for version, entry in (manifest.get("versions") or {}).items():
        for group in VERSIONED:
            if isinstance(entry.get(group), dict):
                targets.append((group, version, entry))
    if isinstance(manifest.get("graphics"), dict):
        targets.append(("graphics", None, manifest))
    for group, version, holder in targets:
        pin = effective(checkout, group, version)
        if pin != shipped(checkout, group, version):
            holder[group] = _merge(holder[group], pin)
            written.append(label(group, version))
    if written:
        atomic_write(path, _dump(manifest) + ("\n" if text.endswith("\n") else ""))
    _save(checkout, [])
    checkout.__dict__.pop("manifest", None)
    return written
