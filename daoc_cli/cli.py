"""The `daoc` command tree: group registration, routing and exit codes.

Groups. GROUPS is the one ordered list of groups, in help order. An entry is
(name, group), where group is a module or object exposing `register(groups)`;
`groups` is the top-level argparse subparsers object. register adds its own group parser and
actions and sets `func` defaults with the signature `handler(args, checkout)
-> int`. A group whose choice help is argparse.SUPPRESS (dev) is left out of
the help listing.

Passthrough. admin, progress and graphics hand their arguments to another
tool untouched, `--` and option-looking arguments included. They are routed
before parsing, not with argparse.REMAINDER (which still parses options that
come first): when argv[0] names one of them, only the group name is parsed
and the rest arrives as `args.passthrough` (a list; None for every other group).

Exit codes: 0 ok; DaocError prints `daoc: <msg>` on stderr and exits with its
code (1 failure, 2 usage or refused); argparse usage errors exit 2;
KeyboardInterrupt exits 130.

`daoc --version` prints the Checkout's release (version.txt) and runs no group,
even when one follows it.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

from daoc_cli.checkout import Checkout
from daoc_cli import client, dev, game, graphics, overview, self_install, server
from daoc_cli.server_tools import admin, progress
from daoc_cli.errors import DaocError, say

GROUPS = (
    ("server", server),
    ("client", client),
    ("game", game),
    ("admin", admin),
    ("progress", progress),
    ("graphics", graphics),
    ("self-install", self_install),
    ("dev", dev),
)
PASSTHROUGH = frozenset(("admin", "progress", "graphics"))


def build_parser() -> Tuple[argparse.ArgumentParser, "argparse._SubParsersAction"]:
    """Return (parser, groups subparsers)."""
    parser = argparse.ArgumentParser(
        prog="daoc",
        description="Offline DAoC on macOS: the server, the client and its graphics patches.",
    )
    parser.add_argument("--version", action="store_true",
                        help="print the daoc release of this checkout and exit")
    groups = parser.add_subparsers(dest="group", title="groups")
    for _, module in GROUPS:
        module.register(groups)
    # Python 3.9's help prints a SUPPRESSed choice as "==SUPPRESS==", so drop
    # hidden groups from the listing and from the metavar; they still parse.
    visible = [a for a in groups._choices_actions if a.help != argparse.SUPPRESS]
    groups._choices_actions[:] = visible
    groups.metavar = "{" + ",".join(a.dest for a in visible) + "}"
    return parser, groups


def _exit_code(e: SystemExit) -> int:
    if e.code is None:
        return 0
    if isinstance(e.code, int):
        return e.code
    print(e.code, file=sys.stderr)
    return 1


def _dispatch(argv: Sequence[str], root: Optional[Union[str, Path]]) -> int:
    parser, groups = build_parser()
    if not argv:
        return overview.show(Checkout(root))
    argv = list(argv)
    passthrough = None
    if argv[0] in PASSTHROUGH:
        argv, passthrough = argv[:1], argv[1:]
    args = parser.parse_args(argv)
    args.passthrough = passthrough
    if args.version:
        print(f"daoc {Checkout(root).version}")
        return 0
    if args.group is None:
        parser.error("a group is required")
    func = getattr(args, "func", None)
    if func is None:
        groups.choices[args.group].error(f"an action is required (see daoc {args.group} --help)")
    return func(args, Checkout(root))


def main(argv: Optional[Sequence[str]] = None, *, root: Optional[Union[str, Path]] = None) -> int:
    """Run daoc with argv (default sys.argv[1:]) against the Checkout at root
    (default: the one holding this package). Returns the exit code."""
    try:
        return _dispatch(sys.argv[1:] if argv is None else argv, root)
    except DaocError as e:
        say(e.msg)
        return e.code
    except SystemExit as e:
        return _exit_code(e)
    except KeyboardInterrupt:
        return 130
