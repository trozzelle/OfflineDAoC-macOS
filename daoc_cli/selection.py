"""The Selection: which Game this Checkout is set up for, and its Default client.

Kept in the gitignored <checkout>/.daoc/selection.json:

    {"game": "0.36b", "client": "new", "switching_to": null}

`switching_to` names the Game a `daoc game switch` is moving to until it
finishes. Without the file, the Selection is inferred from the installs (a
Checkout set up before game versions existed), else the Shipped default in
manifest.json applies.
"""
import json
from typing import Any, Dict, NamedTuple, Optional

from daoc_cli import games, pins
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError
from daoc_cli.files import atomic_write, sha256
from daoc_cli.games import Game

FILE = "selection.json"


class Selection(NamedTuple):
    game: Game
    client: str
    switching_to: Optional[Game] = None
    # The client a pending switch was asked for (--client), so its rerun keeps it.
    switching_client: Optional[str] = None


def _path(checkout: Checkout):
    return checkout.state / FILE


def _parse(checkout: Checkout, data: Any) -> Selection:
    if not isinstance(data, dict) or data.get("client") not in games.CLIENTS:
        raise DaocError("no game and client")
    game = games.parse(str(data.get("game", "")))
    games.check(checkout, game)
    switching = data.get("switching_to")
    target = None
    if switching is not None:
        target = games.parse(str(switching))
        games.check(checkout, target)
    asked = data.get("switching_client")
    if asked is not None and asked not in games.CLIENTS:
        raise DaocError(f"unknown client {asked!r}")
    return Selection(game, data["client"], target, asked if target else None)


def fallback(checkout: Checkout) -> Selection:
    """The Selection the installs were set up for, else the Shipped default."""
    inferred = infer(checkout)
    if inferred is not None:
        return inferred
    game, client = games.default(checkout)
    return Selection(game, client)


def load(checkout: Checkout) -> Selection:
    """The file's Selection, else the inferred one, else the Shipped default."""
    path = _path(checkout)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback(checkout)
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {path}: {e}") from None
    try:
        return _parse(checkout, data)
    except DaocError as e:
        raise DaocError(f"{path} names no valid selection ({e.msg}); "
                        "choose one with daoc game switch <game>") from None


def save(checkout: Checkout, sel: Selection) -> None:
    data: Dict[str, Any] = {
        "game": sel.game.name,
        "client": sel.client,
        "switching_to": sel.switching_to.name if sel.switching_to else None,
        "switching_client": sel.switching_client if sel.switching_to else None,
    }
    atomic_write(_path(checkout), json.dumps(data, indent=2) + "\n")


def require_original(checkout: Checkout, what: str) -> None:
    """DaocError 2 unless the Default client is the Original client: what (bench,
    graphics patches) only works on it."""
    if load(checkout).client != "original":
        raise DaocError(f"{what} works on the original client, and the default client is the new "
                        "one; make the original client the default with: "
                        "daoc client install --client original", 2)


def _version_of_release(checkout: Checkout, release_version: str,
                        prefer: Optional[str] = None) -> Optional[str]:
    """The game Version whose original_client release is release_version: prefer
    when it is one of them (0.37 keeps 0.36's release), else the oldest."""
    found = [v for v in games.versions(checkout)
             if (games.entry(checkout, v).get("original_client") or {}).get("version") == release_version]
    return prefer if prefer in found else (found[0] if found else None)


def _edition_on_disk(checkout: Checkout, version: str) -> Optional[str]:
    """The Edition whose pristine game.dll the Original client holds."""
    for name in ("game.dll.orig", "game.dll"):
        dll = checkout.app_dir / name
        if dll.is_file():
            sha = sha256(dll)
            for edition in games.EDITIONS:
                if sha == games.edition_sha(checkout, Game(version, edition)):
                    return edition
            return None
    return None


def original_game(checkout: Checkout, prefer: Optional[str] = None) -> Optional[Game]:
    """The Game the Original client install holds; None when it holds no known build.
    An install of a release several Versions share is the prefer Version's, when it is one."""
    if not checkout.app_dir.is_dir():
        return None
    record = pins.installed(checkout, "original_client")
    if record is None:
        dll = checkout.app_dir / "game.dll.orig"
        if not dll.is_file():
            dll = checkout.app_dir / "game.dll"
        if not dll.is_file() or sha256(dll) != pins.LEGACY_CLIENT["game_dll_sha256"]:
            return None
        record = pins.LEGACY_CLIENT
    version = _version_of_release(checkout, str(record.get("version")), prefer)
    if version is None:
        return None
    edition = record.get("edition")
    if edition not in games.EDITIONS:
        edition = _edition_on_disk(checkout, version)
    return Game(version, edition) if edition else None


def new_game(checkout: Checkout) -> Optional[Game]:
    """The Game the New client install was made for; None without one."""
    record = pins.installed(checkout, "new_client")
    if not record:
        return None
    try:
        game = games.parse(str(record.get("game", "")))
        games.check(checkout, game)
    except DaocError:
        return None
    return game


def infer(checkout: Checkout) -> Optional[Selection]:
    """The Selection the installs were set up for; None when they name none.
    The Original client wins when both clients are installed."""
    game = original_game(checkout)
    if game is not None:
        return Selection(game, "original")
    game = new_game(checkout)
    if game is not None:
        return Selection(game, "new")
    return None
