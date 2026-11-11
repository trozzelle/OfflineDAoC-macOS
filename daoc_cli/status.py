"""`daoc status --json`: the overview as one JSON object, for the OfflineDAoC app.

Offline, read-only and quick enough to poll: no network, no git, no secret
read. Schema 1; a value daoc cannot tell is null. Hidden from help.
"""
import argparse
import json
from typing import Any, Dict

from daoc_cli import client_runtime, keychain, saves, selection, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

SCHEMA = 1


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser("status", help=argparse.SUPPRESS,
                          description="The overview as one JSON object, for the OfflineDAoC app.")
    p.add_argument("--json", action="store_true", help="print the JSON object")
    p.set_defaults(func=handle)


def _game(game: Any) -> Dict[str, str]:
    return {"name": game.name, "version": game.version, "edition": game.edition}


def snapshot(checkout: Checkout) -> Dict[str, Any]:
    try:
        sel = selection.load(checkout)
    except DaocError:
        sel = selection.fallback(checkout)
    running, detail = server.status(checkout)
    try:
        client_running = client_runtime.running_client(checkout)
    except DaocError:
        client_running = None
    try:
        wine = checkout.flavour
    except DaocError:
        wine = None
    try:
        save = saves.edition(checkout)
    except DaocError:
        save = None
    return {
        "schema": SCHEMA,
        "version": checkout.version,
        "home": str(checkout.home),
        "game": _game(sel.game),
        "client": sel.client,
        "switching_to": sel.switching_to.name if sel.switching_to else None,
        "installed": {
            "server": (checkout.server_dir / "daoc-server.sh").is_file(),
            # client install records the flavour last: until then it is not installed.
            "original_client": (checkout.client_root.is_dir() and checkout.launcher_app.is_dir()
                                and checkout.flavour_file.is_file()),
            "new_client": checkout.new_client_root.is_dir(),
        },
        "wine": wine,
        "server": {"running": running, "detail": detail},
        "client_running": client_running,
        "account_saved": keychain.saved(),
        "save": save,
    }


def handle(args: argparse.Namespace, checkout: Checkout) -> int:
    if not args.json:
        raise DaocError("daoc status needs --json (run daoc for the overview)", 2)
    print(json.dumps(snapshot(checkout), indent=2))
    return 0
