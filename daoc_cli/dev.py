"""`daoc dev`: maintainer actions, hidden from help.

e2e runs the scripted end-to-end acceptance (see e2e). ship-pins writes the
effective pins into manifest.json, for a maintainer to commit.
"""
import argparse

from daoc_cli import e2e, edition_sql, pins
from daoc_cli.checkout import Checkout


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser("dev", help=argparse.SUPPRESS,
                          description="Maintainer actions: the acceptance run, pin shipping "
                                      "and the Sluaghbinder world overlay.")
    actions = p.add_subparsers(dest="action", title="actions")
    a = actions.add_parser(
        "e2e", help="end-to-end acceptance run on ports 20300/20400",
        description="Install what is missing, boot the server on ports 20300/20400, create "
                    "an account, launch the client and check the login reaches the server. "
                    "Evidence goes to evidence/.",
    )
    a.add_argument("account", nargs="?", help="account to create or reuse (default: e2e<time>)")
    a.add_argument("password", nargs="?", help=f"its password (default: {e2e.DEFAULT_PASSWORD})")
    a.add_argument("--client", choices=("original", "new"), default="original",
                   help="client to run (new: the server stays on 10300, which must be free)")
    a.set_defaults(func=_e2e)
    a = actions.add_parser("ship-pins", help="write the effective pins into manifest.json",
                           description="Write the effective pins into manifest.json and "
                                       "clear the Local pins.")
    a.set_defaults(func=_ship_pins)
    a = actions.add_parser(
        "edition-sql", help="write the Sluaghbinder world overlay for a game version",
        description="Download the version's original_client release and write "
                    "server/world/editions/<version>/sluaghbinder.sql from the difference "
                    "between its Sluaghbinder and Classic classes databases.",
    )
    # dest is not `version`: that name belongs to `daoc --version`.
    a.add_argument("game_version", metavar="VERSION", help="game version, e.g. 0.36")
    a.set_defaults(func=_edition_sql)


def _e2e(args: argparse.Namespace, checkout: Checkout) -> int:
    return e2e.run(checkout, args.account, args.password, args.client)


def _ship_pins(args: argparse.Namespace, checkout: Checkout) -> int:
    written = pins.ship(checkout)
    if not written:
        print("nothing to ship")
        return 0
    for name in written:
        group, _, version = name.partition("@")
        print(f"shipped {name} {pins.short(group, pins.shipped(checkout, group, version or None))}")
    print("now commit manifest.json")
    return 0


def _edition_sql(args: argparse.Namespace, checkout: Checkout) -> int:
    edition_sql.generate(checkout, args.game_version)
    return 0
