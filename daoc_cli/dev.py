"""`daoc dev`: maintainer actions, hidden from help.

e2e runs the scripted end-to-end acceptance (see e2e). ship-pins writes the
effective pins into manifest.json, for a maintainer to commit.
"""
import argparse

from daoc_cli import e2e, pins
from daoc_cli.checkout import Checkout


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser("dev", help=argparse.SUPPRESS,
                          description="Maintainer actions: the acceptance run and pin shipping.")
    actions = p.add_subparsers(dest="action", title="actions")
    a = actions.add_parser(
        "e2e", help="end-to-end acceptance run on ports 20300/20400",
        description="Install what is missing, boot the server on ports 20300/20400, create "
                    "an account, launch the client and check the login reaches the server. "
                    "Evidence goes to evidence/.",
    )
    a.add_argument("account", nargs="?", help="account to create or reuse (default: e2e<time>)")
    a.add_argument("password", nargs="?", help=f"its password (default: {e2e.DEFAULT_PASSWORD})")
    a.set_defaults(func=_e2e)
    a = actions.add_parser("ship-pins", help="write the effective pins into manifest.json",
                           description="Write the effective pins into manifest.json and "
                                       "clear the Local pins.")
    a.set_defaults(func=_ship_pins)


def _e2e(args: argparse.Namespace, checkout: Checkout) -> int:
    return e2e.run(checkout, args.account, args.password)


def _ship_pins(args: argparse.Namespace, checkout: Checkout) -> int:
    written = pins.ship(checkout)
    if not written:
        print("nothing to ship")
        return 0
    for group in written:
        print(f"shipped {group} {pins.short(group, pins.shipped(checkout, group))}")
    print("now commit manifest.json")
    return 0
