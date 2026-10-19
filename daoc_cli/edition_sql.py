"""`daoc dev edition-sql <version>`: the Sluaghbinder overlay for a game Version.

The server repo builds the Classic classes world. Upstream ships both
Editions' databases inside the Version's b release archive:
runtime/data/opendaoc.sqlite3.db (Sluaghbinder) and
editions/<version>-no-custom-class/runtime/data/opendaoc.sqlite3.db (Classic
classes); from 0.37 a release is an update of an older one and ships none, so
the two are given (made with the server repo's apply-release-update.py). diff()
turns what the Sluaghbinder database has on top of the Classic one into SQL,
which build-release.sh applies to a copy of the server repo's world
(defaults/world-sluaghbinder.sqlite). It refuses any difference outside
ALLOWED, so the overlay can never carry anything but the Edition's own rows;
widen ALLOWED only for Sluaghbinder rows, with a comment saying why.
"""
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from daoc_cli import pins, release
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, say
from daoc_cli.files import sha256

# Table -> the only "Key" whose row may differ (None: any row). Upstream's
# no_custom_class_database() (source/tools/build_release_036.py) makes the
# Classic database from the Sluaghbinder one by exactly these changes.
ALLOWED: Dict[str, Optional[str]] = {
    "ServerProperty": "enable_sluaghbinder",
    "Mob": None,
    "ClassXSpecialization": None,
}
# Tables whose rows are matched by a natural key rather than their primary key:
# the server repo's world builds its own ids for them.
NATURAL_KEY = {"ServerProperty": "Key"}
# Bookkeeping, not world: upstream's patcher records each world update it applied (with its
# time) in offline_patch_log, so two databases updated apart never match there.
NOT_WORLD = {"offline_patch_log"}

OUT = Path("server") / "world" / "editions"
DB = "runtime/data/opendaoc.sqlite3.db"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def literal(value: Any) -> str:
    """value as an SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _tables(con: sqlite3.Connection) -> List[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _key_columns(con: sqlite3.Connection, table: str) -> Tuple[List[str], List[str]]:
    """(all columns, key columns): the natural key, else the primary key, else every column."""
    info = list(con.execute(f"PRAGMA table_info({_q(table)})"))
    columns = [r[1] for r in info]
    if table in NATURAL_KEY:
        return columns, [NATURAL_KEY[table]]
    pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
    return columns, pk or columns


def _rows(con: sqlite3.Connection, table: str, columns: Sequence[str],
          key: Sequence[str]) -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    select = ", ".join(_q(c) for c in columns)
    rows = {}
    for values in con.execute(f"SELECT {select} FROM {_q(table)}"):
        row = dict(zip(columns, values))
        rows[tuple(row[k] for k in key)] = row
    return rows


def _where(key: Sequence[str], values: Tuple[Any, ...]) -> str:
    return " AND ".join(f"{_q(k)}={literal(v)}" for k, v in zip(key, values))


def _sort_key(value: Tuple[Any, ...]) -> Tuple[Any, ...]:
    return tuple((v is None, str(v)) for v in value)


def diff(b_db: Path, plain_db: Path) -> List[str]:
    """SQL that turns the Classic database's rows into the Sluaghbinder one's,
    ordered by table, then key. DaocError when anything outside ALLOWED differs."""
    b = sqlite3.connect(f"file:{b_db}?mode=ro", uri=True)
    plain = sqlite3.connect(f"file:{plain_db}?mode=ro", uri=True)
    try:
        b_tables, plain_tables = set(_tables(b)) - NOT_WORLD, set(_tables(plain)) - NOT_WORLD
        refused = [f"{t} (table only in one edition)" for t in sorted(b_tables ^ plain_tables)]
        statements: List[str] = []
        for table in sorted(b_tables & plain_tables):
            columns, key = _key_columns(b, table)
            new, old = _rows(b, table, columns, key), _rows(plain, table, columns, key)
            out, rows_differing = [], []
            for k in sorted(set(new) | set(old), key=_sort_key):
                if k in new and k not in old:
                    names = ", ".join(_q(c) for c in columns)
                    values = ", ".join(literal(new[k][c]) for c in columns)
                    out.append(f"INSERT INTO {_q(table)} ({names}) VALUES ({values});")
                elif k in old and k not in new:
                    out.append(f"DELETE FROM {_q(table)} WHERE {_where(key, k)};")
                elif new[k] != old[k]:
                    changed = ", ".join(f"{_q(c)}={literal(new[k][c])}"
                                        for c in columns if new[k][c] != old[k][c])
                    out.append(f"UPDATE {_q(table)} SET {changed} WHERE {_where(key, k)};")
                else:
                    continue
                rows_differing.append((new.get(k) or old.get(k)))
            if not out:
                continue
            allowed_key = ALLOWED.get(table, "")
            if table not in ALLOWED:
                refused.append(f"{table} ({len(out)} rows)")
            elif allowed_key is not None:
                others = sorted({str(r.get("Key")) for r in rows_differing} - {allowed_key})
                if others:
                    refused.append(f"{table} rows {', '.join(others)}")
            statements += out
        if refused:
            raise DaocError("the Sluaghbinder database differs outside the edition's own rows: "
                            + "; ".join(refused) + " (see edition_sql.ALLOWED)")
        return statements
    finally:
        b.close()
        plain.close()


def render(statements: Sequence[str], b_sha: str, plain_sha: str) -> str:
    """The overlay file: a header naming both sources, then one transaction."""
    return "\n".join([
        "-- generated by daoc dev edition-sql: the Sluaghbinder edition's rows on top of the",
        "-- Classic classes world. Do not edit; regenerate it.",
        f"-- Sluaghbinder database sha256 {b_sha}",
        f"-- Classic classes database sha256 {plain_sha}",
        "BEGIN;",
        *statements,
        "COMMIT;",
    ]) + "\n"


def _extract(archive: Path, member: str, dest: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        try:
            src = zf.open(member)
        except KeyError:
            raise DaocError(f"{archive.name} has no {member}") from None
        with src, dest.open("wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    return dest


def generate(checkout: Checkout, version: str,
             fetch_url: Optional[release.Downloader] = None,
             dbs: Optional[Tuple[Path, Path]] = None) -> Path:
    """Write server/world/editions/<version>/sluaghbinder.sql from the Version's
    original_client release, or from dbs (Sluaghbinder, Classic classes) when
    given; returns its path. A Version whose release is an update of an older
    one's (0.37 on) ships no databases, so it needs dbs."""
    with tempfile.TemporaryDirectory(prefix="daoc-edition-") as tmp:
        if dbs is None:
            b_db, plain_db = _release_dbs(checkout, version, Path(tmp), fetch_url)
        else:
            b_db, plain_db = dbs
        statements = diff(b_db, plain_db)
        text = render(statements, sha256(b_db), sha256(plain_db))
    out = checkout.root / OUT / version / "sluaghbinder.sql"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    say(f"wrote {out.relative_to(checkout.root)} ({len(statements)} statements)")
    return out


def _release_dbs(checkout: Checkout, version: str, tmp: Path,
                 fetch_url: Optional[release.Downloader]) -> Tuple[Path, Path]:
    pin = pins.effective(checkout, "original_client", version)
    if pin["version"].rstrip("bc") != version:
        raise DaocError(
            f"game version {version}'s original client is the v{pin['version']} release, so its "
            "databases are that version's; give this version's own with --b-db and --plain-db "
            "(the server repo's tools/world/apply-release-update.py makes them from the "
            "release's game patch)", 2)
    archive = release.download_release(pin, checkout.downloads / f"v{pin['version']}",
                                       fetch_url=fetch_url or release.download)
    root = pin["root_folder"]
    return (_extract(archive, f"{root}/{DB}", tmp / "b.db"),
            _extract(archive, f"{root}/editions/{version}-no-custom-class/{DB}", tmp / "plain.db"))
