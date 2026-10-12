"""The `daoc` command tree: group registration, routing and exit codes.

Groups. GROUPS is the one ordered list of groups, in help order. An entry is
(name, module). A group module exposes `register(groups)`, where `groups` is
the top-level argparse subparsers object: it adds its own group parser and
actions and sets `func` defaults with the signature `handler(args, checkout)
-> int`. Porting a group is one import plus swapping None for the module in its
entry. A group whose module is None gets a bare parser with its BARE_HELP line:
it shows in help, and invoking it is a usage error. A group whose choice help
is argparse.SUPPRESS (dev) is left out of the help listing.

Passthrough. admin, progress and graphics hand their arguments to another
tool untouched, `--` and option-looking arguments included. They are routed
before parsing, not with argparse.REMAINDER (which still parses options that
come first): when argv[0] names one of them and its module is registered, only
the group name is parsed and the rest arrives as `args.passthrough` (a list;
None for every other group).

Exit codes: 0 ok; DaocError prints `daoc: <msg>` on stderr and exits with its
code (1 failure, 2 usage or refused); argparse usage errors exit 2;
KeyboardInterrupt exits 130.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence, Set, Tuple, Union

from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

GROUPS = (
    ("server", None),
    ("client", None),
    ("admin", None),
    ("progress", None),
    ("graphics", None),
    ("dev", None),
)

# Help lines, used only for groups whose module is not in GROUPS yet.
BARE_HELP = {
    "server": "install, run and update the local OpenDAoC server",
    "client": "install, launch and update the game client",
    "admin": "manage the running server (daoc-admin passthrough)",
    "progress": "saved-progress tools (daoc-progress passthrough)",
    "graphics": "optional graphics patches (daoc-gfx passthrough)",
    "dev": argparse.SUPPRESS,
}

PASSTHROUGH = frozenset(("admin", "progress", "graphics"))


def build_parser() -> Tuple[argparse.ArgumentParser, "argparse._SubParsersAction", Set[str]]:
    """Return (parser, groups subparsers, names of bare groups)."""
    parser = argparse.ArgumentParser(
        prog="daoc",
        description="Offline DAoC on macOS: the server, the client and its graphics patches.",
    )
    groups = parser.add_subparsers(dest="group", title="groups")
    bare = set()
    for name, module in GROUPS:
        if module is not None:
            module.register(groups)
            continue
        help_line = BARE_HELP[name]
        description = None if help_line == argparse.SUPPRESS else help_line
        groups.add_parser(name, help=help_line, description=description)
        bare.add(name)
    # Python 3.9's help prints a SUPPRESSed choice as "==SUPPRESS==", so drop
    # hidden groups from the listing and from the metavar; they still parse.
    visible = [a for a in groups._choices_actions if a.help != argparse.SUPPRESS]
    groups._choices_actions[:] = visible
    groups.metavar = "{" + ",".join(a.dest for a in visible) + "}"
    return parser, groups, bare


def _exit_code(e: SystemExit) -> int:
    if e.code is None:
        return 0
    if isinstance(e.code, int):
        return e.code
    print(e.code, file=sys.stderr)
    return 1


def _dispatch(argv: Sequence[str], root: Optional[Union[str, Path]]) -> int:
    parser, groups, bare = build_parser()
    if not argv:
        parser.print_help(sys.stdout)
        return 0
    argv = list(argv)
    passthrough = None
    if argv[0] in PASSTHROUGH and argv[0] not in bare:
        argv, passthrough = argv[:1], argv[1:]
    args = parser.parse_args(argv)
    args.passthrough = passthrough
    if args.group is None:
        parser.error("a group is required")
    func = getattr(args, "func", None)
    if func is None:
        group_parser = groups.choices[args.group]
        if args.group in bare:
            group_parser.error(f"the {args.group} group is not available yet")
        group_parser.error(f"an action is required (see daoc {args.group} --help)")
    return func(args, Checkout(root))


def main(argv: Optional[Sequence[str]] = None, *, root: Optional[Union[str, Path]] = None) -> int:
    """Run daoc with argv (default sys.argv[1:]) against the Checkout at root
    (default: the one holding this package). Returns the exit code."""
    try:
        return _dispatch(sys.argv[1:] if argv is None else argv, root)
    except DaocError as e:
        print(f"daoc: {e.msg}", file=sys.stderr)
        return e.code
    except SystemExit as e:
        return _exit_code(e)
    except KeyboardInterrupt:
        return 130
