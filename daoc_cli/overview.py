"""`daoc` with no arguments: what is installed, what is pinned, what to run.

Offline only: nothing here touches the network. "Built from" is read from what
each install records about itself, and shows `unknown` when it records nothing
usable:
  - Server: the pin `daoc server install` records in the install
    (pins.INSTALLED) once a build succeeds. An install built before that record
    existed names no upstream ref, so built-from is unknown.
  - Client: the pin recorded in the install (pins.INSTALLED); an install made
    before that record falls back to the pristine game.dll, kept as game.dll.orig
    once patched, whose sha256 is compared with the pin's `game_dll_sha256`.
  - Graphics: the HEAD commit of the upstream/graphics clone.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from daoc_cli import files, pins, proc, server, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

NOT_INSTALLED = "not installed"
UNKNOWN = "unknown"


def _git(args: Sequence[str], cwd: Path) -> Optional[str]:
    """`git <args>` in cwd, stdout stripped; None when cwd is not a git
    checkout of its own (never a parent's) or git fails."""
    if not (cwd / ".git").exists():
        return None
    try:
        result = proc.git(cwd, *args, check=False)
    except DaocError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _sha256(path: Path) -> Optional[str]:
    try:
        return files.sha256(path)
    except OSError:
        return None


def _server_install(checkout: Checkout) -> str:
    if not checkout.server_dir.is_dir():
        return NOT_INSTALLED
    try:
        version = (checkout.server_dir / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return f"present (port build {version})" if version else "present"


def _server_running(checkout: Checkout) -> str:
    state, detail = server.status(checkout)
    if state is None:
        return f"{UNKNOWN} ({detail})"
    if state:
        return "yes" + detail[len("running"):]
    return "no"


def _built_from(checkout: Checkout, group: str, pin: Dict[str, Any]) -> Tuple[str, Optional[bool]]:
    """(label, the install was built from pin); matches is None when unknown."""
    if group == "server":
        if not checkout.server_dir.is_dir():
            return NOT_INSTALLED, None
        record = pins.installed(checkout, group)
        if record is None:
            return UNKNOWN, None
        return pins.short(group, record), updates.same(group, record, pin)
    if group == "client":
        if not checkout.app_dir.is_dir():
            return NOT_INSTALLED, None
        record = pins.installed(checkout, group)
        if record is not None:
            return pins.short(group, record), updates.same(group, record, pin)
        dll = checkout.app_dir / "game.dll.orig"
        if not dll.is_file():
            dll = checkout.app_dir / "game.dll"
        sha = _sha256(dll) if dll.is_file() else None
        want = pin.get("game_dll_sha256")
        if sha is None or not want:
            return UNKNOWN, None
        if sha == want:
            return pins.short(group, pin), True
        shipped = pins.shipped(checkout, group)
        if sha == shipped.get("game_dll_sha256"):
            return pins.short(group, shipped), False
        return f"game.dll {sha[:12]}", False
    if not checkout.graphics_src.is_dir():
        return NOT_INSTALLED, None
    head = _git(["rev-parse", "HEAD"], checkout.graphics_src)
    if not head:
        return UNKNOWN, None
    return head[:12], head == pin.get("ref")


def _behind(checkout: Checkout) -> Optional[str]:
    """Commits on the upstream branch not in HEAD, as of the last fetch."""
    count = _git(["rev-list", "--count", "HEAD..@{u}"], checkout.root)
    if count is None or not count.isdigit():
        return None
    upstream = _git(["rev-parse", "--abbrev-ref", "@{u}"], checkout.root) or "upstream"
    n = int(count)
    return f"{n} commit{'' if n == 1 else 's'} behind {upstream} (as of the last fetch)"


def _table(rows: List[Sequence[str]]) -> List[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + r[-1] for r in rows]


def _commands() -> List[Tuple[str, str]]:
    from daoc_cli import cli  # cli imports this module

    _, groups = cli.build_parser()
    return [(a.dest, a.help or "") for a in groups._choices_actions if a.dest != "dev"]


def show(checkout: Checkout) -> int:
    lines = [f"daoc checkout {checkout.root}", ""]
    status = [
        ("Server install:", _server_install(checkout)),
        ("Server running:", _server_running(checkout)),
        ("Client install:", NOT_INSTALLED if not checkout.client_root.is_dir() else "present"),
    ]
    behind = _behind(checkout)
    if behind is not None:
        status.append(("Checkout:", behind))
    width = max(len(k) for k, _ in status)
    lines += [f"{k.ljust(width)}  {v}" for k, v in status]

    rows = [("Pin", "Shipped", "Local", "Built from", "")]
    for group in pins.GROUPS:
        pin = pins.effective(checkout, group)
        local = pins.local(checkout, group)
        built, matches = _built_from(checkout, group, pin)
        rows.append((
            group,
            pins.short(group, pins.shipped(checkout, group)),
            pins.short(group, local) if local is not None else "-",
            built,
            "rebuild due" if matches is False else "",
        ))
    lines += [""] + [line.rstrip() for line in _table(rows)]

    commands = _commands()
    width = max(len(name) for name, _ in commands)
    lines += ["", "Commands:"]
    lines += [f"  daoc {name.ljust(width)}  {help_line}".rstrip() for name, help_line in commands]
    lines += ["", "Run `daoc <command> --help` for its actions (admin and progress need",
              "the Server install, graphics the Client install)."]
    print("\n".join(lines))
    return 0
