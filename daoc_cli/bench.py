"""`daoc client bench`: the client performance gate.

Starts from a stopped client, logs the benchmark character in (client start,
credentials from the login Keychain), settles 45 s, then plays for <seconds>:
NPC interaction + movement through a town (drive). Frame times come from the
present probe (client/tools/frametime: one timestamp per presented Metal frame)
over exactly the play window.

PASS = average FPS >= 60 and p95 frame time <= 16.7 ms (<= 17.0 ms when the
renderer reports vsync on). 1%-low FPS is reported, not gated. The run is
invalid (exit 2) if the probe saw no frames, the renderer state is unknown, or
the character did not move away from the last NPC it interacted with.

The bench needs GM rights for /jump and /target on NPCs: it raises the account
to gm for the run and restores the previous role afterwards. A marker file
records the raise until the restore succeeds; if the server was gone at the
end, the next run restores the account first (or run the printed command).
Requires: a running server, mingw-w64 (input helper), Xcode command line tools
(probe).
"""
import argparse
import json
import math
import os
import re
import signal
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

from daoc_cli import client_runtime, proc, selection, server
from daoc_cli.checkout import Checkout, wine_env
from daoc_cli.errors import DaocError, say

MAKE = "/usr/bin/make"
SETTLE = 45
MIN_FRAMES = 100
MIN_MOVED = 300
DEFAULT_NPCS = "Qunilan Aideen Freagus Llyn Eleri"
VSYNC_RE = re.compile(rb"\(vsync (on|off), maxFps [0-9]+\)")

# Scan codes: W=0x11 fwd, S=0x1F back, LEFT=0xE04B, RIGHT=0xE04D (E0-extended:
# a bare 0x4B/0x4D is NUMPAD4/NUMPAD6)
HELD_KEYS = ("0x11", "0x1F", "0xE04B", "0xE04D")
ROUTE = (("0xE04B", 900), ("0x11", 6000), ("0xE04D", 1500), ("0x11", 5000),
         ("0xE04B", 2400), ("0x11", 6000))


class Invalid(Exception):
    """The run cannot be judged: exit 2 with `INVALID: <reason>` on stdout."""


# --- verdict ---------------------------------------------------------------

def verdict(ts: Sequence[int], vsync: str, tag: str, play_secs: int, npc: str,
            moved: int) -> Tuple[List[str], int]:
    """(result lines, exit code) for probe timestamps (ns) over the play window."""
    ft = [(b - a) / 1e6 for a, b in zip(ts, ts[1:])]           # ms
    if len(ft) < MIN_FRAMES:
        return [f"INVALID: only {len(ft)} frames in the window"], 2
    span = (ts[-1] - ts[0]) / 1e9
    s = sorted(ft)
    n = len(ft)

    def pct(q: float) -> float:
        return s[min(n - 1, int(q * n))]

    low1 = s[int(0.99 * n):]
    avg_fps = n / span
    p95 = pct(0.95)
    limit = 17.0 if "vsync on" in vsync else 16.7
    lines = [
        f"[{tag}] renderer {vsync}; play window {play_secs}s, {n} frames over {span:.1f}s",
        f"  avg FPS {avg_fps:.1f} | frame time mean {sum(ft) / n:.2f} ms, p50 {pct(.5):.2f}, "
        f"p95 {p95:.2f}, p99 {pct(.99):.2f}, max {s[-1]:.1f}",
        f"  1%-low FPS {1000 / (sum(low1) / len(low1)):.1f} (diagnostic) | "
        f"frames > 50 ms: {sum(1 for x in ft if x > 50)}",
        f"  movement: ended {moved} units from the last NPC interacted with ({npc})",
    ]
    if moved < MIN_MOVED:
        return lines + ["INVALID: the character did not move away from the NPC"], 2
    ok = avg_fps >= 60 and p95 <= limit
    lines.append(f"GATE: {'PASS' if ok else 'FAIL'} (avg >= 60 FPS, p95 <= {limit} ms)")
    return lines, 0 if ok else 1


# --- gm raise ----------------------------------------------------------------

def marker(checkout: Checkout) -> Path:
    """Account raised to gm and not yet restored."""
    return checkout.server_dir / "run" / "bench-gm-raised"


def _admin(checkout: Checkout, *args: str):
    return proc.run([server.tool(checkout, "daoc-admin"), *args], check=False)


def _setrole(checkout: Checkout, account: str, role: str) -> bool:
    return _admin(checkout, "accounts", "set-role", account, role).returncode == 0


def restore_leftover(checkout: Checkout) -> None:
    """Restore an account an earlier run left at gm."""
    mark = marker(checkout)
    if not mark.is_file():
        return
    prev = mark.read_text().strip()
    if not _setrole(checkout, prev, "player"):
        raise Invalid(f"cannot restore {prev} to player (left at gm by an earlier run)")
    mark.unlink()
    say(f"restored {prev} to player (left at gm by an earlier run)")


def restore(checkout: Checkout) -> None:
    """Restore the account the marker names; the marker goes only on success."""
    mark = marker(checkout)
    if not mark.is_file():
        return
    account = mark.read_text().strip()
    if _setrole(checkout, account, "player"):
        mark.unlink()
        return
    admin = server.tool(checkout, "daoc-admin")
    print(f"WARNING: {account} is still gm; the next daoc client bench restores it, or run:\n"
          f"  '{admin}' accounts set-role '{account}' player", file=sys.stderr, flush=True)


def raise_gm(checkout: Checkout, account: str) -> None:
    """Raise a player to gm, writing the marker first."""
    result = _admin(checkout, "accounts", "show", account, "--json")
    try:
        role = json.loads(result.stdout or "")["role"] if result.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        role = None
    if role is None:
        raise Invalid(f"cannot read the role of {account}")
    if role == "player":
        marker(checkout).write_text(account + "\n")
        if not _setrole(checkout, account, "gm"):
            raise Invalid(f"cannot raise {account} to gm")


# --- input drive ---------------------------------------------------------------

def drive(checkout: Checkout, seconds: int, state: Path) -> None:
    """Scripted play: NPC interaction + movement.

    Each cycle teleports next to a townsfolk NPC (/jump, GM), targets it
    (/target, GM: NPCs within 800 units), faces it from a step away and
    right-clicks it, which is the game's interact action (a merchant opens its
    trade window), then closes the window and runs a forward/turn movement
    pattern through the town. The last thing each cycle does is walk, so the
    character always ends the run away from the NPC it last interacted with.

    DAOC_BENCH_NPCS overrides the NPC list (space-separated, unique names in the
    character's region). Default: the town in Connacht (Hibernia, region 200).
    """
    helper = checkout.root / "client" / "input-helper" / "sendinput.exe"
    # Input must come from the game's own wineserver: follow DAOC_WINE_HOME /
    # DAOC_WINEPREFIX (the Checkout does).
    wine = checkout.wine_home / "bin" / "wine"
    env = wine_env(checkout.wine_home, checkout.prefix)
    npcs = (os.environ.get("DAOC_BENCH_NPCS") or DEFAULT_NPCS).split()

    def si(*args: str) -> None:
        proc.run([wine, helper, *args], env=env, check=False)

    end = time.monotonic() + seconds
    n = 0
    try:
        while time.monotonic() < end:
            npc = npcs[n % len(npcs)]
            si("chat", f"/jump to {npc}"); time.sleep(2)
            si("chat", f"/target {npc}"); time.sleep(1)
            si("chat", "/face"); time.sleep(1)
            si("sc", "0x1F", "down", "900")             # step back so the NPC is in view
            si("chat", "/face"); time.sleep(1)
            si("rclick", "0.50", "0.47"); time.sleep(0.5)  # interact: the NPC's upper body,
            si("rclick", "0.50", "0.53")                # lower for short races
            state.write_text(npc + "\n")
            time.sleep(3)
            si("sc", "0x01", "down", "50")              # Esc: close the NPC window
            si("sc", "0x1F", "down", "600")
            for code, ms in ROUTE:
                if time.monotonic() >= end:
                    break
                si("sc", code, "down", str(ms))
            n += 1
        si("sc", "0x11", "down", "4000")                # always end walking away
    finally:
        # Release every key the pattern holds, so an aborted run never leaves
        # the character running into a wall.
        for code in HELD_KEYS:
            si("sc", code, "up")
    say(f"bench drive: {n} interaction cycles in {seconds}s")


# --- probe and checks ----------------------------------------------------------

def _lines(path: Path) -> List[bytes]:
    return path.read_bytes().splitlines()


def _moved(db: Path, char: str, npc: str) -> int:
    con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    try:
        row = con.execute("SELECT Region, Xpos, Ypos FROM DOLCharacters WHERE Name = ?",
                          (char,)).fetchone()
        if not row:
            raise Invalid(f"character {char} not found in {db}")
        region, x, y = row
        mobs = con.execute("SELECT X, Y FROM Mob WHERE Name = ? AND Region = ?",
                           (npc, region)).fetchall()
    except sqlite3.Error as e:
        raise Invalid(f"cannot read {db}: {e}") from None
    finally:
        con.close()
    if len(mobs) != 1:
        raise Invalid(f"NPC '{npc}' has {len(mobs)} Mob rows in region {region} (need exactly 1)")
    return int(math.hypot(x - mobs[0][0], y - mobs[0][1]))


def _server_up(checkout: Checkout) -> bool:
    return _admin(checkout, "status").returncode == 0


def _build(checkout: Checkout) -> None:
    if proc.run([MAKE, "-s", "-C", checkout.root / "client" / "input-helper", "sendinput.exe"],
                check=False).returncode != 0:
        raise Invalid("cannot build the input helper (brew install mingw-w64)")
    if proc.run([MAKE, "-s", "-C", checkout.root / "client" / "tools" / "frametime"],
                check=False).returncode != 0:
        raise Invalid("cannot build the frametime probe")


def _bench(checkout: Checkout, seconds: int, tag: str, account: str, out: Path,
           arm: Callable[[], None]) -> int:
    ftlog = out / "ftlog"
    last_npc = out / "last-npc"
    window = out / "window.ns"
    # The bench character is the one client start logs in with (DAOC_CHARACTER,
    # else the most recently played).
    char = client_runtime.character(checkout)
    if char is None:
        raise Invalid("the game account has no character; create one first (daoc client start "
                      "opens character select)")
    os.environ["DAOC_CHARACTER"] = char

    _build(checkout)
    if not _server_up(checkout):
        raise Invalid(f"server not running ({checkout.server_dir})")
    restore_leftover(checkout)
    arm()   # signal handlers only once no earlier run's raise is pending
    for p in (last_npc, window):
        if p.exists():
            p.unlink()
    if ftlog.exists():
        for f in ftlog.iterdir():
            f.unlink()
    try:
        ftlog.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise Invalid(f"cannot create {ftlog}") from None
    say(f"[{tag}] character {char}; output in {out}")

    client_runtime.stop(checkout)
    try:
        raise_gm(checkout, account)

        os.environ["DAOC_FTLOG_DIR"] = str(ftlog)
        try:
            client_runtime.start(checkout, retries=3)
        except DaocError:
            raise Invalid("client never entered the world") from None
        time.sleep(SETTLE)
        logs = sorted(ftlog.glob("ftlog-*.txt"), key=lambda p: p.stat().st_size, reverse=True)
        if not logs:   # the game's presenter writes the most
            raise Invalid("frametime probe wrote nothing (was ftlog.dylib injected?)")
        f = logs[0]
        l0 = len(_lines(f))
        time.sleep(2)
        if len(_lines(f)) <= l0:
            raise Invalid(f"probe file is not growing: {f}")
        gpid = f.stem[len("ftlog-"):]
        mlog = checkout.app_dir / "mtld3d-logs" / f"game-{gpid}.log"
        try:
            found = [m.group(0).decode() for m in VSYNC_RE.finditer(mlog.read_bytes())]
        except OSError:
            found = []
        if not found:
            raise Invalid(f"renderer vsync/frame-cap state not found (mtld3d log for pid {gpid})")
        vsync = found[-1]

        l0 = len(_lines(f))
        t0 = int(time.time())
        drive(checkout, seconds, last_npc)
        t1 = int(time.time())
        time.sleep(1)
        lines = _lines(f)
        window.write_bytes(b"".join(line + b"\n" for line in lines[l0:]))
        # A server that died mid-run leaves the client rendering a disconnected world.
        if not _server_up(checkout):
            raise Invalid("server stopped during the play window")

        client_runtime.stop(checkout)   # logout saves the character's position
    finally:
        restore(checkout)
    npc = last_npc.read_text().strip() if last_npc.is_file() else ""
    if not npc:
        raise Invalid("bench drive recorded no NPC interaction")
    moved = _moved(checkout.server_dir / "data" / "opendaoc.sqlite3.db", char, npc)
    ts = [int(line) for line in _lines(window) if line.strip()]
    result, code = verdict(ts, vsync, tag, t1 - t0, npc, moved)
    for line in result:
        print(line, flush=True)
    return code


def run(checkout: Checkout, seconds: int, tag: str) -> int:
    """0 pass, 1 fail, 2 invalid. The gm raise is restored on return, on an
    error, and on SIGINT/SIGTERM/SIGHUP."""
    # Like client start: on a terminal, a missing Game account is asked for once.
    account = os.environ.get("DAOC_BENCH_ACCOUNT") or client_runtime.credentials()[0]
    out = Path(os.environ.get("DAOC_BENCH_OUT") or tempfile.mkdtemp(prefix=f"daoc-bench-{tag}."))

    def on_signal(signum: int, _frame: object) -> None:
        restore(checkout)
        raise SystemExit(130)

    previous = {}

    def arm() -> None:
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[s] = signal.signal(s, on_signal)

    try:
        return _bench(checkout, seconds, tag, account, out, arm)
    except Invalid as e:
        print(f"INVALID: {e}", flush=True)
        return 2
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


def _handle(args: argparse.Namespace, checkout: Checkout) -> int:
    selection.require_original(checkout, "daoc client bench")
    return run(checkout, args.seconds, args.tag)


def _positive(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n <= 0:
        raise argparse.ArgumentTypeError(f"not a positive number of seconds: {value}")
    return n


def register(actions: "argparse._SubParsersAction") -> None:
    a = actions.add_parser(
        "bench",
        help="the client performance gate (exit 0 pass, 1 fail, 2 invalid)",
        description="Log the benchmark character in, settle 45 s, play for --seconds "
                    "(NPC interaction + movement) and gate on the probe's frame times: "
                    "PASS = avg >= 60 FPS and p95 <= 16.7 ms (17.0 ms with vsync on). "
                    "Run from a GUI Terminal with the server running.",
    )
    a.add_argument("--seconds", type=_positive, default=300, help="play window (default 300)")
    a.add_argument("--tag", default="bench", help="label for the result lines (default bench)")
    a.set_defaults(func=_handle)
