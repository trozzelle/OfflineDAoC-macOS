"""`daoc` with no arguments: what is installed, what is pinned, what to run.

Offline only: nothing here touches the network. "Built from" is read from what
each install records about itself (see pins.built_from), and shows `unknown`
when it records nothing usable.
"""
from typing import List, Optional, Sequence, Tuple

from daoc_cli import mtld3d, pins, proc, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError


def _server_install(checkout: Checkout) -> str:
    if not checkout.server_dir.is_dir():
        return pins.NOT_INSTALLED
    try:
        version = (checkout.server_dir / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    return f"present (port build {version})" if version else "present"


def _server_running(checkout: Checkout) -> str:
    state, detail = server.status(checkout)
    if state is None:
        return f"{pins.UNKNOWN} ({detail})"
    if state:
        return "yes" + detail[len("running"):]
    return "no"


def _newer_release(checkout: Checkout) -> Optional[str]:
    """The newest release tag, as of the last fetch, when HEAD does not contain it."""
    tags = proc.git_out(checkout.root, "tag", "--list", "v[0-9]*", "--sort=-v:refname")
    if not tags:
        return None
    tag = tags.splitlines()[0]
    try:
        contained = proc.git(checkout.root, "merge-base", "--is-ancestor", tag, "HEAD", check=False)
    except DaocError:
        return None
    if contained.returncode != 1:  # 0: HEAD has it; anything else: git could not tell
        return None
    return f"{tag} available (as of the last fetch): git checkout {tag}"


def _table(rows: List[Sequence[str]]) -> List[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    return ["  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + r[-1] for r in rows]


def _commands() -> List[Tuple[str, str]]:
    from daoc_cli import cli  # cli imports this module

    _, groups = cli.build_parser()
    return [(a.dest, a.help or "") for a in groups._choices_actions if a.dest != "dev"]


def _mtld3d(checkout: Checkout) -> str:
    """The current flavour's Wine's mtld3d (mtld3d.state), or - without that Wine."""
    try:
        flavour = checkout.flavour
        wine_home, _ = checkout.flavour_paths(flavour)
        if not (wine_home / "bin" / "wine").is_file():
            return "-"
        return mtld3d.state(wine_home, flavour)
    except DaocError as e:
        return f"{pins.UNKNOWN} ({e.msg})"


def show(checkout: Checkout) -> int:
    lines = [f"daoc checkout {checkout.root}", ""]
    status = [
        ("Server install:", _server_install(checkout)),
        ("Server running:", _server_running(checkout)),
        ("Client install:", pins.NOT_INSTALLED if not checkout.client_root.is_dir() else "present"),
        ("mtld3d:", _mtld3d(checkout)),
    ]
    newer = _newer_release(checkout)
    if newer is not None:
        status.append(("Checkout:", newer))
    width = max(len(k) for k, _ in status)
    lines += [f"{k.ljust(width)}  {v}" for k, v in status]

    rows = [("Pin", "Shipped", "Local", "Built from", "")]
    for group in pins.GROUPS:
        pin = pins.effective(checkout, group)
        local = pins.local(checkout, group)
        built, matches = pins.built_from(checkout, group, pin)
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
