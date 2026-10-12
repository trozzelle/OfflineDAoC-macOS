"""`daoc graphics …`: optional graphical patches for the installed client, from
the pinned OfflineDAoC-macOS-graphics project (the graphics pin).

Everything after `graphics` goes to the pinned daoc-gfx untouched; no
arguments means `select` (the checklist). Nothing here runs unless called:
client install never pulls the graphics project. The first call clones the
pinned commit into upstream/graphics/; every call checks that checkout is at
the pin with no local changes (its d3d9.dll ends up loaded by the game), then
runs its daoc-gfx against this Checkout's client, wine and prefix
(DAOC_WINE_HOME / DAOC_WINEPREFIX override the last two, as they do for the
launcher). Each patch, and what turning it off restores, is in the graphics
project's README.

`graphics update` is daoc's own action, reserved here, and never reaches
daoc-gfx.
"""
import argparse
import sys
from pathlib import Path

from daoc_cli import pins, proc
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

PYTHON = "/usr/bin/python3"


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "graphics",
        help="optional graphics patches (daoc-gfx passthrough)",
        description="Run the pinned daoc-gfx against this checkout's client; "
        "no arguments opens the patch checklist (select).",
    )
    p.set_defaults(func=handle)


def _git(src: Path, *args: str) -> str:
    return proc.run(["git", "-C", str(src), *args]).stdout.strip()


def ensure_checkout(checkout: Checkout) -> Path:
    """Make checkout.graphics_src a clean clone at the effective graphics pin;
    return it. Status lines go to stderr."""
    pin = pins.effective(checkout, "graphics")
    repo, ref = pin["repo"], pin["ref"]
    src = checkout.graphics_src
    if not (src / ".git").is_dir():
        print(f"== graphics: cloning {repo.rstrip('/').rsplit('/', 1)[-1]} at {ref[:12]}", file=sys.stderr)
        src.parent.mkdir(parents=True, exist_ok=True)
        proc.run(["git", "clone", "--quiet", repo, str(src)])
    # Refuse edited or untracked files: they would run (or, for d3d9.dll, be
    # copied next to game.dll) as if they were the pinned commit.
    if _git(src, "status", "--porcelain"):
        raise DaocError(
            f'{src} has local changes (git -C "{src}" status); '
            "remove that folder to re-clone the pinned commit"
        )
    if _git(src, "rev-parse", "HEAD") != ref:
        print(f"== graphics: checking out pinned {ref[:12]}", file=sys.stderr)
        _git(src, "fetch", "--quiet", "origin")
        _git(src, "checkout", "--quiet", "--detach", ref)
    actual = _git(src, "rev-parse", "HEAD")
    if actual != ref:
        raise DaocError(f"{src} is at {actual[:12]}, pinned {ref[:12]}")
    return src


def gfx_argv(checkout: Checkout, src: Path, args: list) -> list:
    return [
        PYTHON, str(src / "daoc-gfx"),
        "--app", str(checkout.app_dir),
        "--wine", str(checkout.wine_home),
        "--prefix", str(checkout.prefix),
        *(args or ["select"]),
    ]


def handle(args: argparse.Namespace, checkout: Checkout) -> int:
    passthrough = list(args.passthrough or [])
    if passthrough[:1] == ["update"]:
        raise DaocError("graphics update is not available yet", 2)
    if not (checkout.app_dir / "game.dll").is_file():
        raise DaocError(f"no client in {checkout.app_dir} — run daoc client install")
    src = ensure_checkout(checkout)
    # No chdir: relative --archives paths, the checklist's archive prompt and
    # relative DAOC_WINE_HOME / DAOC_WINEPREFIX resolve against the caller's
    # directory (Checkout already resolved the env overrides against it).
    proc.execv(gfx_argv(checkout, src, passthrough))
