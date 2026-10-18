"""The Server install's save across a game switch.

The save is <server>/data/opendaoc.sqlite3.db. Its Edition is its own
enable_sluaghbinder property. Which Game it was last moved into is recorded in
data/daoc-game (written after each save step of a switch); a save without that
record belongs to the Selection it was played under.

Every change goes through daoc-progress or a copy into data/progress-backups/,
whose folders daoc labels with daoc-game.json ({"game": "<the Game the backed-up
save belonged to>", "at": ...}) so `daoc game switch --restore` can pick one
made under the right Version.
"""
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import games, proc, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, say
from daoc_cli.files import atomic_write
from daoc_cli.games import Game

SAVE_FILE = "opendaoc.sqlite3.db"
META = "daoc-game.json"
MARKER = "daoc-game"
SIDECARS = ("-wal", "-shm", "-journal")


def _data(checkout: Checkout) -> Path:
    return checkout.server_dir / "data"


def _backups_dir(checkout: Checkout) -> Path:
    return _data(checkout) / "progress-backups"


def exists(checkout: Checkout) -> bool:
    return (_data(checkout) / SAVE_FILE).is_file()


def edition(checkout: Checkout) -> Optional[str]:
    """The save's Edition from its enable_sluaghbinder property; None without a save."""
    path = _data(checkout) / SAVE_FILE
    if not path.is_file():
        return None
    # Read-only cannot open a WAL-mode save without its -wal/-shm (it may not create
    # them), which is how a restored backup arrives. Without a -wal file everything is
    # in the main file, so reading it as immutable is exact.
    query = "mode=ro" if path.with_name(path.name + "-wal").exists() else "mode=ro&immutable=1"
    try:
        con = sqlite3.connect(f"file:{path}?{query}", uri=True)
        try:
            row = con.execute("SELECT Value FROM ServerProperty WHERE \"Key\"='enable_sluaghbinder'").fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise DaocError(f"cannot read {path}: {e}") from None
    # The server treats a missing property as on (ImportEngine.SluaghbinderEnabled).
    on = row is None or str(row[0]).strip().lower() != "false"
    return "sluaghbinder" if on else "classic"


def save_game(checkout: Checkout, default: Game) -> Game:
    """The Game the save was last moved into (data/daoc-game), else default."""
    try:
        return games.parse((_data(checkout) / MARKER).read_text(encoding="utf-8").strip())
    except (OSError, DaocError):
        return default


def mark(checkout: Checkout, game: Game) -> None:
    atomic_write(_data(checkout) / MARKER, game.name + "\n")


def _label(folder: Path, game: Game) -> None:
    atomic_write(folder / META, json.dumps({"game": game.name, "at": datetime.now().isoformat(
        timespec="seconds")}, indent=2) + "\n")


def inspect(checkout: Checkout) -> Dict[str, int]:
    """daoc-progress inspect data --json."""
    result = proc.run([server.tool(checkout, "daoc-progress"), "inspect", _data(checkout), "--json"])
    try:
        counts = json.loads(result.stdout)
    except ValueError:
        raise DaocError(f"daoc-progress inspect gave no JSON: {result.stdout!r}") from None
    if not isinstance(counts, dict):
        raise DaocError(f"daoc-progress inspect gave no JSON object: {result.stdout!r}")
    return counts


def upgrade(checkout: Checkout, previous: Game, target_edition: str, leave_bots: bool) -> Path:
    """Move the save into this build's world for target_edition (daoc-progress
    upgrade, which backs it up first); label the backup with previous, the Game the
    save belonged to. Returns the backup folder."""
    argv = [server.tool(checkout, "daoc-progress"), "upgrade", f"--edition={target_edition}"]
    if leave_bots:
        argv.append("--leave-sluaghbinder-bots")
    result = proc.run(argv)
    proc.replay(result.stdout)
    report = next((line.split("Report:", 1)[1].strip() for line in (result.stdout or "").splitlines()
                   if line.startswith("Done. Report:")), None)
    if not report:
        raise DaocError("daoc-progress upgrade did not name its backup")
    folder = Path(report).parent
    _label(folder, previous)
    return folder


def backups(checkout: Checkout) -> List[Tuple[Path, Dict[str, Any]]]:
    """Labelled backups, newest first."""
    found = []
    root = _backups_dir(checkout)
    for folder in sorted(root.iterdir(), reverse=True) if root.is_dir() else []:
        try:
            meta = json.loads((folder / META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and (folder / SAVE_FILE).is_file():
            found.append((folder, meta))
    return found


def _move_save(checkout: Checkout, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    data = _data(checkout)
    for suffix in ("",) + SIDECARS:
        src = data / (SAVE_FILE + suffix)
        if src.exists():
            shutil.move(str(src), str(dest / src.name))


def _new_backup(checkout: Checkout, kind: str) -> Path:
    return _backups_dir(checkout) / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{kind}"


def fresh(checkout: Checkout, previous: Game) -> Path:
    """Move the save aside (labelled previous); the next start makes a fresh one."""
    folder = _new_backup(checkout, "fresh")
    _move_save(checkout, folder)
    _label(folder, previous)
    (_data(checkout) / MARKER).unlink(missing_ok=True)
    say(f"save moved aside to {folder}; the next server start creates a fresh world")
    return folder


def restore(checkout: Checkout, name: str, version: str, current: Optional[Game] = None) -> None:
    """Put a labelled backup made under version back as the save; the current
    save (labelled current) is moved aside first."""
    match = next(((f, m) for f, m in backups(checkout) if f.name == name), None)
    if match is None:
        names = ", ".join(f.name for f, _ in backups(checkout)) or "none"
        raise DaocError(f"no labelled backup {name!r} in {_backups_dir(checkout)} (labelled: {names})", 2)
    folder, meta = match
    try:
        made = games.parse(str(meta.get("game")))
    except DaocError:
        raise DaocError(f"backup {name} names no game", 2) from None
    if made.version != version:
        raise DaocError(f"backup {name} was made under {made.name}, not game version {version}", 2)
    if exists(checkout):
        aside = _new_backup(checkout, "before-restore")
        _move_save(checkout, aside)
        if current is not None:
            _label(aside, current)
    for suffix in SIDECARS:
        (_data(checkout) / (SAVE_FILE + suffix)).unlink(missing_ok=True)
    # A save set aside after an unclean stop holds committed rows in its -wal.
    for suffix in ("-wal", ""):
        if (folder / (SAVE_FILE + suffix)).is_file():
            shutil.copy2(folder / (SAVE_FILE + suffix), _data(checkout) / (SAVE_FILE + suffix))
    mark(checkout, made)
    say(f"restored the save from {folder}")
