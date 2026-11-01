"""`daoc dev`: maintainer actions, hidden from help.

e2e runs the scripted end-to-end acceptance (see e2e). ship-pins writes the
effective pins into manifest.json, for a maintainer to commit. pack-server
builds a version's Shipped server pin and packs the prebuilt tarball;
ship-prebuilt writes that tarball's url, size and hash into manifest.json
(the server-prebuilt workflow runs both).
"""
import argparse
from pathlib import Path

from daoc_cli import e2e, edition_sql, games, pins, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.files import sha256


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
        "pack-server", help="build a game version's Shipped server pin and pack the prebuilt tarball",
        description="Build the Shipped server pin of VERSION from source into the data home "
                    "(DAOC_DATA), then pack it as the prebuilt tarball; prints its path.",
    )
    a.add_argument("game_version", metavar="VERSION", help="game version, e.g. 0.37")
    a.add_argument("--out", type=Path, default=Path("dist"), help="folder for the tarball (default: dist)")
    a.set_defaults(func=_pack_server)
    a = actions.add_parser(
        "ship-prebuilt", help="write a prebuilt server tarball's url, size and hash into manifest.json",
        description="Write versions.VERSION.server.prebuilt for a tarball made by pack-server "
                    "from that version's Shipped server pin.",
    )
    a.add_argument("game_version", metavar="VERSION", help="game version, e.g. 0.37")
    a.add_argument("tarball", type=Path, help="the tarball pack-server wrote")
    a.add_argument("url", help="where the release serves it (https://…/<tarball name>)")
    a.set_defaults(func=_ship_prebuilt)
    a = actions.add_parser(
        "edition-sql", help="write the Sluaghbinder world overlay for a game version",
        description="Write server/world/editions/<version>/sluaghbinder.sql from the difference "
                    "between the version's Sluaghbinder and Classic classes databases: those in "
                    "its original_client release, or the two given (a version whose release is "
                    "an update of an older one ships none).",
    )
    # dest is not `version`: that name belongs to `daoc --version`.
    a.add_argument("game_version", metavar="VERSION", help="game version, e.g. 0.36")
    a.add_argument("--b-db", type=Path, help="the Sluaghbinder database (with --plain-db)")
    a.add_argument("--plain-db", type=Path, help="the Classic classes database (with --b-db)")
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


def _known(checkout: Checkout, version: str) -> None:
    if version not in games.versions(checkout):
        raise DaocError(f"no game version {version} (expected one of: "
                        f"{', '.join(games.versions(checkout))})", 2)


def _pack_server(args: argparse.Namespace, checkout: Checkout) -> int:
    _known(checkout, args.game_version)
    pin = pins.shipped(checkout, "server", args.game_version)
    server.install(checkout, args.game_version, pin=pin, from_source=True)
    print(server.pack(checkout, args.game_version, pin["ref"], args.out.resolve()))
    return 0


def _ship_prebuilt(args: argparse.Namespace, checkout: Checkout) -> int:
    version, tarball, url = args.game_version, args.tarball, args.url
    _known(checkout, version)
    if pins.local(checkout, "server", version):
        raise DaocError(f"server@{version} has a Local pin; ship it first (daoc dev ship-pins)", 2)
    want = server.prebuilt_name(version, pins.shipped(checkout, "server", version)["ref"])
    if tarball.name != want:
        raise DaocError(f"{tarball.name} is not the Shipped server@{version}'s tarball ({want})", 2)
    if not url.startswith("https://") or not url.endswith("/" + tarball.name):
        raise DaocError(f"the url must be https and end with /{tarball.name}", 2)
    if not tarball.is_file():
        raise DaocError(f"{tarball} is missing", 2)
    pins.ship_field(checkout, "server", version, "prebuilt",
                    {"url": url, "bytes": tarball.stat().st_size, "sha256": sha256(tarball)})
    print(f"shipped server@{version} prebuilt {tarball.name}")
    print("now commit manifest.json")
    return 0


def _edition_sql(args: argparse.Namespace, checkout: Checkout) -> int:
    if (args.b_db is None) != (args.plain_db is None):
        raise DaocError("give both --b-db and --plain-db, or neither", 2)
    dbs = (args.b_db, args.plain_db) if args.b_db else None
    edition_sql.generate(checkout, args.game_version, dbs=dbs)
    return 0
