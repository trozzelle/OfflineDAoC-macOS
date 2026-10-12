# Updating and saved progress

How to move daoc to a newer release, the server, client and graphics patches to
newer upstream versions, and how to carry your progress (accounts, characters,
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

## Server, client and graphics

Each part has its own update:

```bash
daoc server update --check     # report what moved upstream; change nothing
daoc server update             # move the server to the upstream's latest commit and rebuild
daoc client update             # move the client to the latest OfflineDAoC release
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

`daoc server update` checks the macOS patches still apply before it moves
anything. If the server is running it asks before stopping it. The rebuild
replaces only the program files, so your `config/`, `data/` (accounts,
characters, bots), `logs/` and `navmesh/` stay in place.

### Client

`daoc client update` re-applies the Client patch to the new `game.dll`. If that
`game.dll` is one it doesn't know, it stops with "not a Proven build; it needs a
shipped update" and leaves your client as it was. Graphics patches you had on
are carried across to the new client.

## Saved progress

### Moving progress into new world data

An existing save keeps the world it was created with. If the update ships new
world data (such as the 0.35 sync), `daoc server update` asks whether to move
your progress into it (a Progress upgrade; default no). You can also run it
later with the server stopped:

```bash
daoc progress upgrade
```

This carries over accounts (with their roles), characters, items, money, houses,
guilds, bots and this install's settings. World state such as keep and relic
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
