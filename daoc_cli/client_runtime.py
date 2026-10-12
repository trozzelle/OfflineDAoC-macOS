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

from daoc_cli import files, keychain, proc, watchdog
from daoc_cli.checkout import Checkout, wine_env, wine_is_arm64
from daoc_cli.errors import DaocError, say

PS = "/bin/ps"
PGREP = "/usr/bin/pgrep"
PKILL = "/usr/bin/pkill"
LSOF = "/usr/sbin/lsof"
OPEN = "/usr/bin/open"

# The Launcher appends wine's output here; it is a fixed path, not per-checkout.
WINE_LOG = Path("/tmp/daoc-wine.log")
DEFAULT_RETRIES = 3
DEFAULT_PORT = 10300

# LaunchServices drops the caller's environment, so wine/x87sidecar/FEX/mtld3d/
# Metal HUD knobs must ride on --env. Forward them only when set: an empty
# ROSETTA_X87_PATH would disable the sidecar instead of selecting the bundled one.
# DAOC_WINE_HOME / DAOC_WINEPREFIX are not forwarded raw: the Launcher runs with
# cwd /, so launch_argv sends the Checkout's resolved paths, the same wine that
# kill and game_pids look for the client under.
FORWARD_ENV = ("DAOC_DLL_OVERRIDES", "WINE_COMPATDB", "WINE_LARGE_ADDRESS_AWARE",
               "ROSETTA_X87_PATH", "DAOC_FTLOG_DIR", "DAOC_FPS_OVERLAY")
FORWARD_PREFIXES = ("X87_", "MTL_", "MTLD3D_", "FEX_")

# What the arm64 Wine (Hadron's runtime) runs the client with, as Hadron's own
# launcher does; a caller's value wins. mtld3d is a native d3d9.dll in the arm64
# prefix, so d3d9 is native first (the graphics anisotropy proxy, when on, is
# found first in the client folder). vsync off matches athei's mtld3d in the
# rosetta Wine. FEX_X87REDUCEDPRECISION: the client does its 3D math in x87,
# which FEX otherwise emulates at full 80-bit precision in software; in world
# that held it at ~10-15 FPS, with f64 x87 it runs at ~120 (the 7 FPS Rosetta
# problem x87sidecar solves, in FEX's form).
ARM64_ENV = {
    "DAOC_DLL_OVERRIDES": "mscoree,mshtml=;d3d9=n,b",
    "FEX_DISKCACHE": "1",
    "FEX_X87REDUCEDPRECISION": "1",
    "MTLD3D_NO_CRASH_HANDLER": "1",
    "MTLD3D_CONFIG": "color.hdr.enable=false;present.vsync=off",
    "WINE_LARGE_ADDRESS_AWARE": "1",
}


def wine_defaults(checkout: Checkout) -> Dict[str, str]:
    """Launch environment the Checkout's Wine needs unless the caller sets it."""
    return dict(ARM64_ENV) if wine_is_arm64(checkout.wine_home) else {}


REALMS = {1: "Albion", 2: "Midgard", 3: "Hibernia"}


def _server_log(checkout: Checkout) -> Path:
    return checkout.server_dir / "logs" / "server.log"


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


def credentials() -> Tuple[str, str]:
    """The saved Game account; on first run in a terminal, ask once and save it."""
    try:
        return keychain.read()
    except keychain.NotSaved:
        if not sys.stdin.isatty():
            raise
    keychain.save_interactive()
    return keychain.read()


def _load_character(checkout: Checkout, account: str) -> Optional[Tuple[str, int]]:
    """(name, realm) for account: $DAOC_CHARACTER, else the most recently played;
    None when the account has no character yet (a named one must exist)."""
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
        return None
    return str(row[0]), int(row[1])


def character(checkout: Checkout) -> Optional[str]:
    """The character a start would enter the world as; None: character select."""
    account, _ = credentials()
    chosen = _load_character(checkout, account)
    return chosen[0] if chosen else None


def forwarded_env(environ: Dict[str, str]) -> List[str]:
    names = list(FORWARD_ENV) + sorted(
        k for k in environ if k.startswith(FORWARD_PREFIXES) and k not in FORWARD_ENV)
    args = []
    for name in names:
        if name in environ:
            args += ["--env", f"{name}={environ[name]}"]
    return args


def launch_argv(checkout: Checkout, account: str, password: str,
                chosen: Optional[Tuple[str, int]], game_port: int,
                environ: Dict[str, str]) -> List[str]:
    """Without a character the client logs in and stops at character select."""
    tail = [chosen[0], str(chosen[1])] if chosen else []
    return [
        OPEN, "-n", str(checkout.launcher_app),
        "--env", "WINEDEBUG=" + (environ.get("DAOC_WINEDEBUG") or "trace+frametime"),
        "--env", "DAOC_LAUNCHER_RETRIES=8",
        "--env", f"DAOC_WINE_HOME={checkout.wine_home}",
        "--env", f"DAOC_WINEPREFIX={checkout.prefix}",
        *forwarded_env({**wine_defaults(checkout), **environ}),
        "--args", "wine", "game.dll", "127.0.0.1", str(game_port), "42",
        account, password, *tail,
    ]


def _launch_once(checkout: Checkout, game_port: int, account: str, password: str,
                 chosen: Optional[Tuple[str, int]]) -> None:
    if not checkout.launcher_app.is_dir():
        raise DaocError(f"{checkout.launcher_app} is missing; run daoc client install", 2)
    if chosen:
        say(f"launching {chosen[0]} ({REALMS.get(chosen[1], chosen[1])}) on port {game_port}")
    else:
        say(f"account {account} has no character yet; opening character select on port "
             f"{game_port} so you can create one")
    try:
        proc.run(launch_argv(checkout, account, password, chosen, game_port, dict(os.environ)),
                 cwd=checkout.root)
    except DaocError as e:
        raise DaocError(e.msg, 2) from None


def _game_cputime_cs() -> int:
    result = proc.run([PS, "-Ao", "time=,args="], check=False)
    return watchdog.game_cputime_cs(result.stdout or "")


def _logins(checkout: Checkout, account: str) -> int:
    """Accepted-login lines for account. The server writes "logging on!" before
    it checks the password, so a "Wrong password" after it is checked separately."""
    try:
        text = _server_log(checkout).read_text(errors="replace")
    except OSError:
        return 0
    return len(re.findall(r"User " + re.escape(account) + r" logging on!", text, re.IGNORECASE))


def start(checkout: Checkout, *, retries: int = 1) -> None:
    """Launch until the client enters the world; DaocError when it never does.

    An account without a character is launched to character select instead, and
    succeeds once the server accepts the login: waiting for a world entry would
    kill the client while the character is being created."""
    game_port = default_port(checkout)
    account, password = credentials()
    chosen = _load_character(checkout, account)

    def progress() -> int:
        return _world_entries(checkout) if chosen else _logins(checkout, account)

    tries = 0
    while tries < retries:
        tries += 1
        before, log_offset = progress(), files.size(_server_log(checkout))
        _launch_once(checkout, game_port, account, password, chosen)
        watch = watchdog.start(before, files.size(WINE_LOG), _game_cputime_cs())
        while True:
            time.sleep(watchdog.POLL)
            sample = watchdog.Sample(progress(), files.size(WINE_LOG), _game_cputime_cs())
            verdict, watch = watchdog.step(watch, sample)
            if verdict == watchdog.IN_WORLD:
                if not chosen:
                    if "Wrong password" in files.tail(_server_log(checkout), log_offset):
                        raise DaocError(f"the server rejected the password for {account}; "
                                        "run daoc client login to save the right one", 2)
                    say(f"logged in after {watch.waited}s; create your character at "
                         "character select")
                    return
                say(f"in world after {watch.waited}s")
                return
            if verdict == watchdog.HUNG:
                say(f"hung: wine log static {watch.stall}s, game cpu {watch.busy}cs/10s, "
                     f"not in world; killing tree (try {tries}/{retries})")
                break
            if verdict == watchdog.TIMEOUT:
                say(f"timeout: not in world after {watchdog.CAP}s (try {tries}/{retries}); "
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


def game_pids(checkout: Checkout, wine_home: Optional[Path] = None) -> List[int]:
    """This Checkout's game.dll processes (not the launcher shell or start.exe),
    under wine_home when given, else under the Checkout's Wine.

    CrossOver wine shows only "game.dll <args>" as argv and macOS does not
    expose other processes' environments, so ownership is decided by the files
    a process maps from this Checkout's wine.
    """
    wine_home = os.path.realpath(wine_home or checkout.wine_home)
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
    env = wine_env(checkout.wine_home, checkout.prefix)
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


def stop(checkout: Checkout) -> None:
    """kill, then wait until the server has dropped the Linkdead character (60 s
    after a kill), so the next login is not refused with "still being logged out
    from linkdeath"."""
    slog = _server_log(checkout)
    before = files.size(slog)
    kill(checkout)
    say(f"{time.strftime('%H:%M:%S')} client stopped")
    time.sleep(3)
    if watchdog.linkdead_pending(files.tail(slog, before)):
        for _ in range(45):
            time.sleep(2)
            if not watchdog.linkdead_pending(files.tail(slog, before)):
                say(f"{time.strftime('%H:%M:%S')} server dropped the character")
                break
    # Anything wine-related still alive is a leak (e.g. another prefix's wineserver).
    result = proc.run([PS, "-Ao", "pid=,comm="], check=False)
    for line in (result.stdout or "").splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and re.search(r"wine|x87sidecar|preloader", fields[1]):
            say(f"leftover: {fields[0]} {fields[1]}")


def _start(args: argparse.Namespace, checkout: Checkout) -> int:
    if args.character is not None:
        os.environ["DAOC_CHARACTER"] = args.character
    if args.dry_run:
        name = character(checkout)
        if name:
            print(name)
        else:
            say("no character yet; start opens character select so you can create one")
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
