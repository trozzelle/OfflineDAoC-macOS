"""Shipped pins, Local pins, and which one applies.

A Shipped pin is a group's entry in the tracked manifest.json, minus its
`note`. A user update records a Local pin instead of editing the manifest, so
an updated Checkout stays clean and the next `git pull` never conflicts on it.
Local pins live in the gitignored <checkout>/.daoc/pins.json, one entry per
group:

    {"group": "server", "pin": {...}, "replaces": {...}, "at": "2026-10-11T12:00:00Z"}

`replaces` is the Shipped pin the Local pin was made against. Once a pull
changes that Shipped pin, the Local pin lapses: it is dropped with a one-line
notice and the new Shipped pin applies. Only ship() writes the manifest, for a
maintainer to commit.

The Server and Client installs record the pin they were built from in their
own folder (INSTALLED), so whether an install is up to date is read from the
install, never inferred from the pin.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from daoc_cli.checkout import Checkout
from daoc_cli.files import atomic_write
from daoc_cli.errors import DaocError

GROUPS = ("server", "client", "graphics")

# The field that names a pin in messages; refs are shortened to 12 hex chars.
_SHORT_FIELD = {"server": "ref", "client": "version", "graphics": "ref"}

STORE = "pins.json"
# In the Server and Client install folders: the pin the install was built from.
INSTALLED = ".daoc-pin.json"


def _check_group(group: str) -> None:
    if group not in GROUPS:
        raise DaocError(f"no pin group {group!r} (expected one of: {', '.join(GROUPS)})")


def short(group: str, fields: Optional[Dict[str, Any]]) -> str:
    """The pin's name for messages: 12 chars of `ref`, or the client `version`."""
    _check_group(group)
    value = (fields or {}).get(_SHORT_FIELD[group])
    if value is None:
        return "unknown"
    value = str(value)
    return value[:12] if _SHORT_FIELD[group] == "ref" else value


def shipped(checkout: Checkout, group: str) -> Dict[str, Any]:
    """The group's pin fields from manifest.json (its entry without `note`)."""
    _check_group(group)
    entry = checkout.manifest.get(group)
    if not isinstance(entry, dict):
        raise DaocError(f"manifest.json has no {group} entry")
    return {k: v for k, v in entry.items() if k != "note"}


def _store_path(checkout: Checkout) -> Path:
    return checkout.state / STORE


def _load(checkout: Checkout) -> List[Dict[str, Any]]:
    path = _store_path(checkout)
    try:
        with path.open(encoding="utf-8") as f:
            entries = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {path}: {e}") from None
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


def _entry(entries: List[Dict[str, Any]], group: str) -> Optional[Dict[str, Any]]:
    for entry in entries:
        if entry["group"] == group:
            return entry
    return None


def local(checkout: Checkout, group: str) -> Optional[Dict[str, Any]]:
    """The group's Local pin while it still applies, else None.

    Side-effect free: a lapsed entry is reported as None but left in the store;
    effective() is what drops it and prints the notice.
    """
    _check_group(group)
    entry = _entry(_load(checkout), group)
    if entry is None or entry["replaces"] != shipped(checkout, group):
        return None
    return dict(entry["pin"])


def effective(checkout: Checkout, group: str) -> Dict[str, Any]:
    """The pin that applies: the Local pin while its `replaces` still equals the
    Shipped pin, else the Shipped pin. A lapsed Local pin is dropped from the
    store with a one-line notice on stderr."""
    current = shipped(checkout, group)
    entries = _load(checkout)
    entry = _entry(entries, group)
    if entry is None:
        return current
    if entry["replaces"] == current:
        return dict(entry["pin"])
    _save(checkout, [e for e in entries if e is not entry])
    print(
        f"daoc: Local {group} pin {short(group, entry['pin'])} lapsed; "
        f"Shipped pin {short(group, current)} applies",
        file=sys.stderr,
    )
    return current


def set_local(checkout: Checkout, group: str, fields: Dict[str, Any]) -> None:
    """Record fields as the group's Local pin, made against the current Shipped pin."""
    _check_group(group)
    if not isinstance(fields, dict) or not fields:
        raise DaocError(f"a Local {group} pin needs its pin fields")
    entries = [e for e in _load(checkout) if e["group"] != group]
    entries.append({
        "group": group,
        "pin": {k: v for k, v in fields.items() if k != "note"},
        "replaces": shipped(checkout, group),
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    entries.sort(key=lambda e: GROUPS.index(e["group"]))
    _save(checkout, entries)


def _installed_path(checkout: Checkout, group: str) -> Path:
    if group == "server":
        return checkout.server_dir / INSTALLED
    if group == "client":
        return checkout.client_root / INSTALLED
    raise DaocError(f"the {group} install records no pin")


def installed(checkout: Checkout, group: str) -> Optional[Dict[str, Any]]:
    """The pin the group's install records it was built from; None when it
    records none (no install, an install made before the record, or a build
    that did not finish)."""
    try:
        fields = json.loads(_installed_path(checkout, group).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return fields if isinstance(fields, dict) else None


def record_installed(checkout: Checkout, group: str, fields: Dict[str, Any]) -> None:
    """Record fields as the pin the group's install was built from."""
    atomic_write(_installed_path(checkout, group),
                 json.dumps({k: v for k, v in fields.items() if k != "note"}, indent=2) + "\n")


def forget_installed(checkout: Checkout, group: str) -> None:
    """Drop the install's record before a rebuild changes the install."""
    try:
        _installed_path(checkout, group).unlink()
    except FileNotFoundError:
        pass


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
    return the groups whose manifest entry changed.

    Every other manifest key, each group's `note` and the key order are kept.
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
    for group in GROUPS:
        if group not in manifest:
            continue
        pin = effective(checkout, group)
        if pin != shipped(checkout, group):
            manifest[group] = _merge(manifest[group], pin)
            written.append(group)
    if written:
        atomic_write(path, _dump(manifest) + ("\n" if text.endswith("\n") else ""))
    _save(checkout, [])
    checkout.__dict__.pop("manifest", None)
    return written
