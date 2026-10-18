"""Decisions for `daoc client start`: in world, hung, timed out, or keep waiting.

Pure functions over samples taken every POLL seconds, so the policy is testable
without processes. The client is hung when the wine log has been static for
STALL_LIMIT seconds AND the game burned under BUSY_LIMIT_CS of CPU in the last
POLL seconds; it timed out when CAP seconds pass without a world entry.

Success is a NEW WorldInitRequestHandler line in the server log. A
LoginRequestHandler line alone is not enough: the server logs it even when it
refuses the login ("still being logged out from linkdeath").
"""
from typing import NamedTuple, Tuple

POLL = 10
STALL_LIMIT = 60
BUSY_LIMIT_CS = 50  # 0.5 s of CPU per POLL
CAP = 240

WORLD_MARK = "WorldInitRequestHandler"
LINKDEAD_MARK = "Linkdead player"
DISCONNECTED_MARK = " just disconnected"

IN_WORLD = "in_world"
HUNG = "hung"
TIMEOUT = "timeout"
WAIT = "wait"


class Sample(NamedTuple):
    entries: int   # WorldInitRequestHandler lines in the server log now
    log_size: int  # wine log size in bytes now
    cpu_cs: int    # cumulative game CPU in centiseconds now


class Watch(NamedTuple):
    before: int       # world entries before the launch
    last_size: int
    last_cs: int
    waited: int = 0
    stall: int = 0
    busy: int = 0     # CPU centiseconds in the last poll (for messages)


def start(before: int, log_size: int, cpu_cs: int) -> Watch:
    return Watch(before=before, last_size=log_size, last_cs=cpu_cs)


def step(watch: Watch, sample: Sample) -> Tuple[str, Watch]:
    """Advance one POLL; return (verdict, new watch)."""
    waited = watch.waited + POLL
    if sample.entries > watch.before:
        return IN_WORLD, watch._replace(waited=waited)
    if sample.log_size == watch.last_size:
        stall, last_size = watch.stall + POLL, watch.last_size
    else:
        stall, last_size = 0, sample.log_size
    busy = sample.cpu_cs - watch.last_cs
    new = watch._replace(waited=waited, stall=stall, last_size=last_size,
                         last_cs=sample.cpu_cs, busy=busy)
    if stall >= STALL_LIMIT and busy < BUSY_LIMIT_CS:
        return HUNG, new
    if waited >= CAP:
        return TIMEOUT, new
    return WAIT, new


def world_entries(server_log: str) -> int:
    return sum(1 for line in server_log.splitlines() if WORLD_MARK in line)


def cputime_cs(field: str) -> int:
    """ps `time` ([[dd-]hh:]mm:ss.ss) in centiseconds; seconds, minutes and
    hours only, as the old awk summed them."""
    parts = field.split(":")
    try:
        seconds = float(parts[-1])
        if len(parts) > 1:
            seconds += float(parts[-2]) * 60
        if len(parts) > 2:
            seconds += float(parts[-3].split("-")[-1]) * 3600
    except ValueError:
        return 0
    return int(seconds * 100)


def is_game_process(args: str) -> bool:
    """A game.dll process, not the launcher shell (its argv carries the
    game.dll arguments) nor wine's start.exe."""
    return "game.dll" in args and "MacOS/launch" not in args and "start.exe" not in args


def is_new_client_process(args: str, godot_app: str) -> bool:
    """This Checkout's Godot running the New client: its argv starts with the
    pinned app's binary (not a shell that merely names it)."""
    binary = godot_app.rstrip("/") + "/Contents/MacOS/Godot"
    return args == binary or args.startswith(binary + " ")


def game_cputime_cs(ps_output: str) -> int:
    """Sum of game CPU from `/bin/ps -Ao time=,args=` output."""
    total = 0
    for line in ps_output.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and is_game_process(fields[1]):
            total += cputime_cs(fields[0])
    return total


def linkdead_pending(log_tail: str) -> bool:
    """The kill left a Linkdead character the server has not dropped yet."""
    return LINKDEAD_MARK in log_tail and DISCONNECTED_MARK not in log_tail
