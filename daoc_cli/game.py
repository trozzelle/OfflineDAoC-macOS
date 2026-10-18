"""`daoc game`: the Games this Checkout can be, and `daoc game switch`.

switch moves the one setup to another Game, in this order; each step checks
what is already done, so re-running the same switch resumes it:
  1. Refuse early, touching nothing: an unknown Game; the new client before 0.36
     or on a port other than 10300; an older Version without --restore or
     --fresh-save; both of those; a save whose Sluaghbinder characters (or bots,
     without --leave-sluaghbinder-bots) cannot move into a Classic classes Game.
  2. Record the switch as pending in the Selection, then fetch what is new:
     the Original client's release and the New client (staged beside its
     install). Nothing installed has changed yet.
  3. Stop a running client (waiting out Linkdead), then the server (asking first).
  4. Server: rebuild when the Version's server pin differs from the install;
     record the Edition fresh saves start as.
  5. Save: restore a backup or move it aside when asked; otherwise move it into
     the Game's world (daoc-progress upgrade) unless it is already there.
  6. Clients: bring each installed client (and the default one) to the Game. A
     New client on a Game without one stays installed, unused.
  7. Record the Selection; the switch is no longer pending.
"""
import argparse
from typing import List, Optional

from daoc_cli import client, client_runtime, games, newclient, pins, saves, selection, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, say
from daoc_cli.games import EDITION_TITLES, Game
from daoc_cli.selection import Selection


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "game",
        help="choose the game version and edition (0.35, 0.35b, 0.36, 0.36b)",
        description="List the games this checkout can be, or switch the server, the save and the "
                    "clients to another one.",
    )
    p.set_defaults(func=_show)
    actions = p.add_subparsers(dest="action", title="actions")
    actions.add_parser("list", help="the games, their clients, and the selected one").set_defaults(func=_show)
    a = actions.add_parser(
        "switch", help="move this setup to another game",
        description="Move the server, the save and the installed clients to another game. "
                    "Re-run the same switch to finish one that was interrupted.")
    a.add_argument("game_name", metavar="GAME", help="0.35, 0.35b, 0.36 or 0.36b (b: with the Sluaghbinder)")
    a.add_argument("--client", choices=games.CLIENTS, default=None,
                   help="also make this the default client (installing it if needed)")
    a.add_argument("--leave-sluaghbinder-bots", action="store_true",
                   help="moving to a Classic classes game: leave the Sluaghbinder bots behind")
    older = a.add_mutually_exclusive_group()
    older.add_argument("--restore", metavar="BACKUP",
                       help="moving to an older version: the backup (data/progress-backups/) to play")
    older.add_argument("--fresh-save", action="store_true",
                       help="moving to an older version: set the save aside and start a fresh world")
    a.set_defaults(func=_switch)


def _show(args: argparse.Namespace, checkout: Checkout) -> int:
    return show(checkout)


def _switch(args: argparse.Namespace, checkout: Checkout) -> int:
    return switch(checkout, games.parse(args.game_name), args.client, args.leave_sluaghbinder_bots,
                  args.restore, args.fresh_save)


def show(checkout: Checkout) -> int:
    sel = selection.load(checkout)
    rows = []
    for version in games.versions(checkout):
        clients = "original, new" if games.new_client_supported(checkout, version) else "original"
        for edition in ("classic", "sluaghbinder"):
            g = Game(version, edition)
            mark = "* selected" if g == sel.game else ""
            rows.append((g.name, EDITION_TITLES[edition], clients, mark))
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r[:3], widths)) + "  " + r[3] for r in rows]
    print("\n".join(line.rstrip() for line in lines))
    print(f"\nDefault client: {sel.client}")
    if sel.switching_to:
        print(f"Switch to {sel.switching_to.name} incomplete: run daoc game switch {sel.switching_to.name}")
    return 0


def _older_backups(checkout: Checkout, version: str) -> List[str]:
    return [folder.name for folder, meta in saves.backups(checkout)
            if str(meta.get("game", "")).rstrip("b") == version]


def switch(checkout: Checkout, target: Game, client_name: Optional[str], leave_bots: bool,
           restore: Optional[str], fresh: bool) -> int:
    games.check(checkout, target)
    sel = selection.load(checkout)

    # 1. Refuse early.
    if restore and fresh:
        raise DaocError("--restore and --fresh-save are alternatives; give one", 2)
    supported = games.new_client_supported(checkout, target.version)
    final = client_name or sel.client
    if client_name == "new" and not supported:
        raise DaocError(f"the new client exists from 0.36 (game {target.name} has none)", 2)
    fell_back = final == "new" and not supported
    if fell_back:
        final = "original"
        say(f"the new client exists from 0.36; {target.name} uses the original client "
            "(the new client stays installed)")
    if final == "new" and client_runtime.default_port(checkout) != client_runtime.NEW_PORT:
        raise DaocError(f"the new client only connects to port {client_runtime.NEW_PORT}; set the "
                        "server back to it ($DAOC_PORT, <Port> in config/serverconfig.xml)", 2)
    have_save = saves.exists(checkout)
    save_game = saves.save_game(checkout, sel.game)
    older = have_save and games.order(target.version) < games.order(save_game.version)
    if older and not (restore or fresh):
        made = _older_backups(checkout, target.version)
        raise DaocError(f"the save is from {save_game.name}, newer than {target.name}, and a save cannot "
                        "move to an older version: add --restore <backup> (made under "
                        f"{target.version}: {', '.join(made) or 'none'}) or --fresh-save", 2)
    if restore and restore not in _older_backups(checkout, target.version):
        raise DaocError(f"no backup {restore!r} made under {target.version} "
                        f"(found: {', '.join(_older_backups(checkout, target.version)) or 'none'})", 2)
    if have_save and not (restore or fresh) and target.edition == "classic" \
            and saves.edition(checkout) == "sluaghbinder":
        counts = saves.inspect(checkout)
        if counts.get("sluaghbinder_characters", 0):
            raise DaocError(f"the save has {counts['sluaghbinder_characters']} Sluaghbinder character(s), "
                            f"which {target.name} (classic classes) cannot hold; nothing was changed", 2)
        if counts.get("sluaghbinder_bots", 0) and not leave_bots:
            raise DaocError(f"the save has {counts['sluaghbinder_bots']} Sluaghbinder bot(s); add "
                            "--leave-sluaghbinder-bots to leave them (and what they carry) behind", 2)
    # Installed clients come along; a client is installed only when asked for, or
    # when it becomes the default because the new client has no build for the Game.
    want_original = checkout.client_root.is_dir() or client_name == "original" or fell_back
    want_new = supported and (checkout.new_client_root.is_dir() or client_name == "new")

    # 2. Pending, then fetch what is new.
    selection.save(checkout, sel._replace(switching_to=target))
    if want_original:
        client.install(checkout, game=target, download_only=True)
    if want_new:
        newclient.install(checkout, target, download_only=True)

    # 3. Stop.
    if client_runtime.running_client(checkout):
        client_runtime.stop(checkout)
    server._stop_first(checkout)

    # 4. Server.
    pin = pins.effective(checkout, "server", target.version)
    if pins.built_from(checkout, "server", pin)[1] is not True:
        server.install(checkout, target.version)
    server.set_edition(checkout, target.edition)

    # 5. Save.
    if have_save:
        if fresh:
            saves.fresh(checkout, save_game)
        else:
            if restore:
                saves.restore(checkout, restore, target.version, save_game)
            moved = saves.save_game(checkout, sel.game)
            if moved.version != target.version or saves.edition(checkout) != target.edition:
                saves.upgrade(checkout, moved, target.edition, leave_bots)
            saves.mark(checkout, target)

    # 6. Clients.
    if want_original:
        client.install(checkout, game=target)
    if want_new:
        newclient.install(checkout, target)

    # 7. Done.
    selection.save(checkout, Selection(target, final))
    say(f"switched to {target.name} ({EDITION_TITLES[target.edition]}); default client: {final}")
    return 0
