# Updating and saved progress

How to move daoc to a newer release, switch the game, update the server,
clients and graphics patches, and carry your progress (accounts, characters,
bots) across world updates or from another save.

## daoc itself

Each daoc release is a git tag (`v0.1.0`, `v0.2.0`, …); [CHANGELOG.md](../CHANGELOG.md)
lists what each one changed. After a fetch has seen a newer release, `daoc` shows
it on the `Checkout:` line. To move to it:

```bash
git fetch --tags
daoc                      # Checkout: v0.2.0 available …
git checkout v0.2.0       # the release daoc named
daoc --version
```

A checkout cloned from `main` before releases existed moves onto them the same
way. Your installs, saves and Local pins are not tracked by git, so the checkout
change leaves them alone; if the new release ships new pins, `daoc` shows
"rebuild due" (see [Pins](#pins)).

## Switching games

`daoc game switch <game>` moves this setup to another game: `0.35`, `0.35b`,
`0.36`, `0.36b`, `0.37` or `0.37b` (see [PLAY.md](PLAY.md#choose-the-game)). Your save moves into
the new game's world with a Progress upgrade (below); the previous save is backed
up first and labelled with the game it belonged to.

A save cannot move to an older version. Going back needs one of:

```bash
daoc game switch 0.35b --restore <backup>   # a backup made under 0.35 (the refusal lists them)
daoc game switch 0.35b --fresh-save         # set the current save aside; start a fresh world
```

Backups are in the server's `data/progress-backups/`.

## Server, client and graphics

Updates stay within the selected game version; a newer upstream version (0.38)
needs a daoc release, and `--check` says when one is out. Each part has its own
update:

```bash
daoc server update --check     # report what moved upstream; change nothing
daoc server update             # move the server to the server repo's latest commit for this version, and rebuild
daoc client update             # take the default client's release again if upstream replaced its files
daoc graphics update           # move the Graphics project to its latest commit
```

`--check` works on all three.

### Pins

The versions this repo was tested with are its Shipped pins, in `manifest.json`.
An update records your newer version as a Local pin in `.daoc/pins.json` (not
tracked by git), so it applies only to this checkout. When a newer release brings
a new Shipped pin for that part, your Local pin lapses and the shipped version
applies again.

`daoc` shows both pins, what each install was built from, and "rebuild due" when
they differ: `daoc server install` or `daoc client install` brings that install
to the pin (the client keeps your graphics patches, as an update does).

### Server

The server is built from [OfflineDAoC-macOS-server](https://github.com/trozzelle/OfflineDAoC-macOS-server),
which carries the macOS fixes as commits: `main` for the newest version and a
`macos-<version>` branch for each older one. `daoc server update` follows the
selected version's branch only while it is synced to that version (the server
says which in its source); a branch that moves on to a newer version stops the
update, which says so. If the server is running it asks before stopping it. The rebuild
replaces only the program files, so your `config/`, `data/` (accounts,
characters, bots), `logs/` and `navmesh/` stay in place.

Pins made before the server moved to its own repo named catastrophic-impact's
fork; the first `daoc server install` after the move points `upstream/server/`
at the new repo. A Server install built from one of those pins shows "rebuild
due" until then.

### Client

`daoc client update` re-reads the selected version's release for the default
client; upstream sometimes replaces a release's files under the same tag. For the
original client it re-applies the Client patch to the new `game.dll`. If that
`game.dll` is one it doesn't know, it stops with "not a Proven build; it needs a
shipped update" and leaves your client as it was. Graphics patches you had on
are carried across to the new client. For the new client it downloads the release
again and swaps it in only once complete; the installed client stays until then.
From 0.37 the new client is an update of 0.36c: `daoc` installs the 0.36c release,
then applies the update, checking each file it replaces is the released one.

## Saved progress

### Moving progress into new world data

An existing save keeps the world it was created with. If the update ships new
world data, `daoc server update` asks whether to move your progress into it (a
Progress upgrade, into the selected game's edition; default no). `daoc game
switch` runs it without asking. You can also run it
later with the server stopped:

```bash
daoc progress upgrade
```

This carries over accounts (with their roles), characters, items, money, houses,
guilds, bots and this install's settings; the edition (Sluaghbinder or not) is the
selected game's. World state such as keep and relic
ownership starts fresh. The previous save is backed up to
`data/progress-backups/<time>/` first.

### Bringing progress from elsewhere

To bring progress from an older server folder, or a Windows Offline DAoC folder
containing `runtime/`:

```bash
daoc progress inspect <folder>                    # show what a save holds; changes nothing
daoc progress import <folder> --replace-progress  # replace this server's progress
```

`import` replaces this server's progress and only reads the source.

Undo steps and details are in [server/README.md](../server/README.md#maintenance)
(Maintenance).
