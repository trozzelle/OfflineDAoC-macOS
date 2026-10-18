"""The Games daoc can set up, read from manifest.json (schema 2).

A Game is a Version plus an Edition, named the way upstream names its
releases: `0.36b` is Version 0.36 with the Sluaghbinder, `0.36` the same
Version with the Classic classes only. Each Version is an entry of
manifest.json `versions`, holding its pins (server, original_client,
new_client; new_client is null before 0.36).
"""
import re
from typing import Any, Dict, List, NamedTuple, Tuple

from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

EDITIONS = ("sluaghbinder", "classic")
CLIENTS = ("original", "new")

EDITION_TITLES = {"sluaghbinder": "Sluaghbinder", "classic": "Classic classes"}

_NAME = re.compile(r"(\d+\.\d+)(b?)")


class Game(NamedTuple):
    version: str
    edition: str

    @property
    def name(self) -> str:
        return self.version + ("b" if self.edition == "sluaghbinder" else "")


def parse(name: str) -> Game:
    """A Game from its name: `0.36b` (Sluaghbinder) or `0.36` (Classic classes)."""
    match = _NAME.fullmatch(name or "")
    if match is None:
        raise DaocError(f"{name!r} is not a game: name one like 0.36 (classic classes) "
                        "or 0.36b (with the Sluaghbinder)", 2)
    return Game(match.group(1), "sluaghbinder" if match.group(2) else "classic")


def order(version: str) -> Tuple[int, ...]:
    """A Version's sort key: 0.36 after 0.35, 0.100 after 0.99."""
    return tuple(int(x) for x in version.split("."))


def _versions(checkout: Checkout) -> Dict[str, Any]:
    entries = checkout.manifest.get("versions")
    if not isinstance(entries, dict) or not entries:
        raise DaocError("manifest.json has no game versions (schema 2 `versions`)")
    return entries


def versions(checkout: Checkout) -> List[str]:
    """The Versions this daoc release supports, oldest first."""
    return sorted(_versions(checkout), key=order)


def entry(checkout: Checkout, version: str) -> Dict[str, Any]:
    """The Version's manifest entry; DaocError 2 for a Version daoc doesn't know."""
    found = _versions(checkout).get(version)
    if not isinstance(found, dict):
        raise DaocError(f"daoc doesn't know game version {version} "
                        f"(known: {', '.join(versions(checkout))})", 2)
    return found


def check(checkout: Checkout, game: Game) -> None:
    """DaocError 2 unless the Game's Version is supported."""
    entry(checkout, game.version)


def new_client_supported(checkout: Checkout, version: str) -> bool:
    return isinstance(entry(checkout, version).get("new_client"), dict)


def default(checkout: Checkout) -> Tuple[Game, str]:
    """The Shipped default (Game, client) from manifest.json `default`."""
    value = checkout.manifest.get("default")
    if not isinstance(value, dict) or value.get("client") not in CLIENTS:
        raise DaocError("manifest.json has no valid `default` game and client")
    game = parse(str(value.get("game", "")))
    check(checkout, game)
    return game, value["client"]


def edition_sha(checkout: Checkout, game: Game) -> str:
    """The pristine game.dll sha256 of the Game's Edition."""
    client = entry(checkout, game.version).get("original_client") or {}
    try:
        return client["editions"][game.edition]["game_dll_sha256"]
    except (KeyError, TypeError):
        raise DaocError(f"manifest.json has no {game.edition} game.dll for {game.version}") from None
