"""`daoc client start | stop | kill | login`: run the installed game client.

start opens the Launcher bundle (kept as shell, started through `open -n`) with
`wine game.dll 127.0.0.1 <port> 42 <account> <password> <character> <realm>`,
then watches for a new world entry in the server log and retries a hung or
timed-out client (see watchdog). The character is $DAOC_CHARACTER, else the
account's most recently played one, read from the server's database.

Teardown is scoped to this Checkout: processes are chosen by the files they map
from this Checkout's wine (lsof on `<wine_home>/`), so another checkout's
launcher, client or sidecar is never signalled. ps, pgrep and lsof run by
absolute path: some shells shadow ps with a builtin that misreports translated
processes.
"""
import argparse
import os
import pathlib
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from daoc_cli import keychain, proc, watchdog
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

PS = "/bin/ps"
PGREP = "/usr/bin/pgrep"
PKILL = "/usr/bin/pkill"
LSOF = "/usr/sbin/lsof"
OPEN = "/usr/bin/open"

# The Launcher appends wine's output here; it is a fixed path, not per-checkout.
WINE_LOG = Path("/tmp/daoc-wine.log")
DEFAULT_RETRIES = 3
DEFAULT_PORT = 10300

# LaunchServices drops the caller's environment, so wine/x87sidecar/Metal HUD
# knobs must ride on --env. Forward them only when set: an empty
# ROSETTA_X87_PATH would disable the sidecar instead of selecting the bundled one.
FORWARD_ENV = ("DAOC_WINE_HOME", "DAOC_WINEPREFIX", "DAOC_DLL_OVERRIDES", "WINE_COMPATDB",
               "ROSETTA_X87_PATH", "DAOC_FTLOG_DIR", "DAOC_FPS_OVERLAY")
FORWARD_PREFIXES = ("X87_", "MTL_")

REALMS = {1: "Albion", 2: "Midgard", 3: "Hibernia"}


def _say(msg: str) -> None:
    print(f"daoc: {msg}", file=sys.stderr, flush=True)


def _server_log(checkout: Checkout) -> Path:
    return checkout.server_dir / "logs" / "server.log"


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _world_entries(checkout: Checkout) -> int:
    try:
        text = _server_log(checkout).read_text(errors="replace")
    except OSError:
        return 0
    return watchdog.world_entries(text)


def default_port(checkout: Checkout) -> int:
    """$DAOC_PORT, else <Port> from the server's config (as daoc-server.sh
    reads it), else 10300."""
    value = os.environ.get("DAOC_PORT", "")
    if not value:
        try:
            config = (checkout.server_dir / "config" / "serverconfig.xml").read_text(errors="replace")
        except OSError:
            config = ""
        match = re.search(r"<Port>([0-9]*)</Port>", config)
        value = match.group(1) if match else ""
    try:
        return int(value) if value else DEFAULT_PORT
    except ValueError:
        raise DaocError(f"DAOC_PORT is not a number: {value}", 2) from None


def _credentials() -> Tuple[str, str]:
    """The saved Game account; on first run in a terminal, ask once and save it."""
    try:
        return keychain.read()
    except keychain.NotSaved:
        if not sys.stdin.isatty():
            raise
    keychain.save_interactive()
    return keychain.read()


def _load_character(checkout: Checkout, account: str) -> Tuple[str, int]:
    """(name, realm) for account: $DAOC_CHARACTER, else the most recently played."""
    db = checkout.server_dir / "data" / "opendaoc.sqlite3.db"
    name = os.environ.get("DAOC_CHARACTER", "")
    query = "SELECT Name, Realm FROM DOLCharacters WHERE AccountName = ? COLLATE NOCASE"
    try:
        con = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True)
        try:
            if name:
                row = con.execute(query + " AND Name = ?", (account, name)).fetchone()
            else:
                row = con.execute(query + " ORDER BY LastPlayed DESC, AccountSlot LIMIT 1",
                                  (account,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise DaocError(f"cannot read characters from {db}: {e}", 2) from None
    if not row:
        if name:
            raise DaocError(f"account {account} has no character {name}", 2)
        raise DaocError(f"account {account} has no character; create one in the client first", 2)
    return str(row[0]), int(row[1])


def character(checkout: Checkout) -> str:
    """The character a start would enter the world as."""
    account, _ = _credentials()
    return _load_character(checkout, account)[0]


def _forwarded_env(environ: Dict[str, str]) -> List[str]:
    names = list(FORWARD_ENV) + sorted(
        k for k in environ if k.startswith(FORWARD_PREFIXES) and k not in FORWARD_ENV)
    args = []
    for name in names:
        if name in environ:
            args += ["--env", f"{name}={environ[name]}"]
    return args


def launch_argv(checkout: Checkout, account: str, password: str, name: str, realm: int,
                game_port: int, environ: Dict[str, str]) -> List[str]:
    return [
        OPEN, "-n", str(checkout.launcher_app),
        "--env", "WINEDEBUG=" + (environ.get("DAOC_WINEDEBUG") or "trace+frametime"),
        "--env", "DAOC_LAUNCHER_RETRIES=8",
        *_forwarded_env(environ),
        "--args", "wine", "game.dll", "127.0.0.1", str(game_port), "42",
        account, password, name, str(realm),
    ]


def _launch_once(checkout: Checkout, game_port: int) -> None:
    account, password = _credentials()
    name, realm = _load_character(checkout, account)
    if not checkout.launcher_app.is_dir():
        raise DaocError(f"{checkout.launcher_app} is missing; run daoc client install", 2)
    _say(f"launching {name} ({REALMS.get(realm, realm)}) on port {game_port}")
    try:
        proc.run(launch_argv(checkout, account, password, name, realm, game_port, dict(os.environ)),
                 cwd=checkout.root)
    except DaocError as e:
        raise DaocError(e.msg, 2) from None


def _game_cputime_cs() -> int:
    result = proc.run([PS, "-Ao", "time=,args="], check=False)
    return watchdog.game_cputime_cs(result.stdout or "")


def start(checkout: Checkout, *, character: Optional[str] = None, retries: int = 1,
          port: Optional[int] = None) -> None:
    """Launch until the client enters the world; DaocError when it never does."""
    if character is not None:
        os.environ["DAOC_CHARACTER"] = character
    game_port = port if port is not None else default_port(checkout)
    before = _world_entries(checkout)
    tries = 0
    while tries < retries:
        tries += 1
        _launch_once(checkout, game_port)
        watch = watchdog.start(before, _size(WINE_LOG), _game_cputime_cs())
        while True:
            time.sleep(watchdog.POLL)
            sample = watchdog.Sample(_world_entries(checkout), _size(WINE_LOG), _game_cputime_cs())
            verdict, watch = watchdog.step(watch, sample)
            if verdict == watchdog.IN_WORLD:
                _say(f"in world after {watch.waited}s")
                return
            if verdict == watchdog.HUNG:
                _say(f"hung: wine log static {watch.stall}s, game cpu {watch.busy}cs/10s, "
                     f"not in world; killing tree (try {tries}/{retries})")
                break
            if verdict == watchdog.TIMEOUT:
                _say(f"timeout: not in world after {watchdog.CAP}s (try {tries}/{retries}); "
                     "killing tree")
                break
        kill(checkout)  # launcher loop + this prefix's wine tree
    raise DaocError(f"gave up after {tries} tries")


def _real_wine_home(checkout: Checkout) -> str:
    # Resolved: lsof reports real paths.
    return os.path.realpath(checkout.wine_home)


def _maps_wine_home(pid: int, wine_home: str) -> bool:
    result = proc.run([LSOF, "-a", "-p", str(pid), "-Fn"], check=False)
    return wine_home_mapped(result.stdout or "", wine_home)


def wine_home_mapped(lsof_fn_output: str, wine_home: str) -> bool:
    """lsof -Fn output names a file under wine_home/."""
    mark = "n" + wine_home.rstrip("/") + "/"
    return any(line.startswith(mark) for line in lsof_fn_output.splitlines())


def _pgrep(pattern: str) -> List[int]:
    result = proc.run([PGREP, "-f", pattern], check=False)
    return [int(p) for p in (result.stdout or "").split() if p.isdigit()]


def game_pids(checkout: Checkout) -> List[int]:
    """This Checkout's game.dll processes (not the launcher shell or start.exe).

    CrossOver wine shows only "game.dll <args>" as argv and macOS does not
    expose other processes' environments, so ownership is decided by the files
    a process maps from this Checkout's wine.
    """
    wine_home = _real_wine_home(checkout)
    result = proc.run([PS, "-Ao", "pid=,args="], check=False)
    pids = []
    for line in (result.stdout or "").splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[0].isdigit() and watchdog.is_game_process(fields[1]):
            pid = int(fields[0])
            if _maps_wine_home(pid, wine_home):
                pids.append(pid)
    return pids


def kill(checkout: Checkout) -> None:
    """Tear down this Checkout's client tree and wait for its wineserver to exit,
    so a relaunch never overlaps a previous client."""
    wine_home = _real_wine_home(checkout)
    wineserver = os.path.join(wine_home, "bin", "wineserver")
    env = dict(os.environ, WINEPREFIX=str(checkout.prefix))
    # The app launcher's relaunch loop first, or it respawns wine in the gap. It
    # is a bash script, so this Checkout's bundle path is in its argv.
    proc.run([PKILL, "-f", str(checkout.launcher_app / "Contents" / "MacOS" / "launch")], check=False)
    if os.path.exists(wineserver):
        proc.run([wineserver, "-k"], env=env, check=False)
    # Stragglers wineserver -k missed: game.dll and x87sidecar processes with
    # files mapped from this Checkout's wine.
    for pid in _pgrep(r"game\.dll|x87sidecar"):
        if _maps_wine_home(pid, wine_home):
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    if os.path.exists(wineserver):
        proc.run([wineserver, "-w"], env=env, check=False)


def _log_tail(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def stop(checkout: Checkout) -> None:
    """kill, then wait until the server has dropped the Linkdead character (60 s
    after a kill), so the next login is not refused with "still being logged out
    from linkdeath"."""
    slog = _server_log(checkout)
    before = _size(slog)
    kill(checkout)
    _say(f"{time.strftime('%H:%M:%S')} client stopped")
    time.sleep(3)
    if watchdog.LINKDEAD_MARK in _log_tail(slog, before):
        for _ in range(45):
            if watchdog.DISCONNECTED_MARK in _log_tail(slog, before):
                _say(f"{time.strftime('%H:%M:%S')} server dropped the character")
                break
            time.sleep(2)
    # Anything wine-related still alive is a leak (e.g. another prefix's wineserver).
    result = proc.run([PS, "-Ao", "pid=,comm="], check=False)
    for line in (result.stdout or "").splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and re.search(r"wine|x87sidecar|preloader", fields[1]):
            _say(f"leftover: {fields[0]} {fields[1]}")


def _start(args: argparse.Namespace, checkout: Checkout) -> int:
    if args.character is not None:
        os.environ["DAOC_CHARACTER"] = args.character
    if args.dry_run:
        print(character(checkout))
        return 0
    if args.retries < 1:
        raise DaocError("--retries must be at least 1", 2)
    start(checkout, retries=args.retries)
    return 0


def _stop(args: argparse.Namespace, checkout: Checkout) -> int:
    stop(checkout)
    return 0


def _kill(args: argparse.Namespace, checkout: Checkout) -> int:
    kill(checkout)
    return 0


def _login(args: argparse.Namespace, checkout: Checkout) -> int:
    keychain.save_interactive()
    return 0


def register(actions: "argparse._SubParsersAction") -> None:
    """Add start, stop, kill and login to the client group's actions."""
    p = actions.add_parser("start", help="launch the client into the world",
                           description="Launch the client and wait until the character is in the world.")
    p.add_argument("--character", metavar="NAME",
                   help="character to play (default: $DAOC_CHARACTER, else the last played)")
    p.add_argument("--retries", type=int, default=DEFAULT_RETRIES, metavar="N",
                   help=f"launch attempts for a hung client (default {DEFAULT_RETRIES})")
    p.add_argument("--dry-run", action="store_true", help="print the character and exit")
    p.set_defaults(func=_start)
    p = actions.add_parser("stop", help="stop the client and wait out Linkdead")
    p.set_defaults(func=_stop)
    p = actions.add_parser("kill", help="tear the client down at once")
    p.set_defaults(func=_kill)
    p = actions.add_parser("login", help="save or replace the Game account in the Keychain")
    p.set_defaults(func=_login)
