# daoc-macos

OfflineDAoC server and game client running on macOS, Apple Silicon (arm64) with Rosetta 2 under Wine;
needs Xcode Command Line Tools and cmake (`brew install cmake`) — everything
else is fetched.

DAoC is a property of Mythic Entertainment / Broadsword Online Games (Electronic Arts).
This is unaffiliated fan tooling; the original client and game data remain their property.

Nothing here would exist without the upstream projects — go support them:

- [OpenDAoC](https://github.com/OpenDAoC/OpenDAoC-Core) — the open DAoC server emulator
- [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC) — the playable offline
  bundle built on OpenDAoC; it ships the original 1.127 Windows client, which the
  Client install downloads
- [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots) —
  a pinned OpenDAoC fork (Offline DAoC 0.35) that the Server install builds on
- [athei/wine-build](https://github.com/athei/wine-build) — the CrossOver-based
  macOS Wine the client runs under, with
  [x87sidecar](https://github.com/athei/x87sidecar) (native ARM64 for the
  client's x87 floating point, which Rosetta otherwise emulates slowly) and
  [mtld3d](https://github.com/athei/mtld3d) (Direct3D 9 on Metal)

This repo only adds install scaffolding and macOS compatibility patches.
Server-side patches are GPL v3, like the upstream they modify.

## Set up

Clone the repo, then put the `daoc` command on your PATH:

```bash
git clone <this repo> daoc-macos && cd daoc-macos
./daoc self-install
```

`self-install` writes `~/.local/bin/daoc`, a small wrapper that runs this
checkout's `./daoc`. If `~/.local/bin` is not on your PATH it offers to add this
line to `~/.zprofile` (default no), or you add it yourself:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Run `daoc` with no arguments for an overview: where the checkout is, whether the
Server install and Client install are present, whether the server runs, and each
pin. `daoc <group> --help` lists a group's actions. `admin`, `progress` and
`graphics` hand `--help` to their tool instead, so it works only once the Server
install (`admin`, `progress`) or Client install (`graphics`) exists.

## Install the server

```bash
daoc server install
```

Clones the pinned upstream, checks the macOS patches apply, builds
`server/dist/daoc-server/`. Output is limited to progress steps and errors; add
`--verbose` to also see git progress, compiler/MSBuild warnings and the build
tools' own output.

## Install the client

```bash
daoc client install
```

Downloads the OfflineDAoC release (≈5 GB) and athei's CrossOver Wine build,
applies the Client patch to `game.dll`, and sets up a wine prefix. Re-runs skip
finished steps. The prefix keeps its Windows profile folders (Documents,
Desktop, ...) inside the prefix, so the client never triggers a macOS privacy
prompt for your home folders. Add `--verbose` to see the Wine download's
progress bar and wine's prefix setup logging.

## Play

Start the server (it holds the terminal with the admin screen):

```bash
daoc server start
```

In a **second terminal**, create a Game account, save it, and launch the client:

```bash
daoc admin accounts create <name> <pass>
daoc client login     # saves the Game account in the login Keychain
daoc client start
```

`daoc client login` stores the account in the login Keychain (service
`daoc-offline`); run it again to replace it. If no account is saved yet,
`daoc client start` asks for it the first time. It logs in as `DAOC_CHARACTER`
(or `--character NAME`), else the account's most recently played character
(read from the server database; `--dry-run` prints it and exits), connects to
the `<Port>` in the server's `config/serverconfig.xml` (`DAOC_PORT` overrides),
and relaunches a client that hangs before entering the world (`--retries N`,
default 3). An account with no character yet is logged in to character select
instead, where you create one; the next `daoc client start` enters the world
with it.

Over SSH, the login Keychain is locked for that session even while you are
logged in at the Mac, because macOS unlocks it only for the session you logged
in to. `daoc client login`, `client start` and `client bench` then run
`security unlock-keychain`, which asks for your macOS login password. Without a
terminal (a script, `ssh host daoc …` with no `-t`), they stop and tell you to run
`security unlock-keychain` first. The client still opens on the Mac's own screen,
so someone has to be logged in there.

If the client crashes before the splash, the launcher relaunches it on its own
(up to 10 tries; each attempt is traced to `/tmp/daoc-launcher.log`). Exit with
`/quit` in chat. If the client runs longer than ~3 minutes with no login
screen, note what is on screen and check `tail -50 /tmp/daoc-wine.log`.
Two known causes of a client that sits without logging in are described in
`docs/CLIENT-NOTES.md`: an unanswered macOS privacy prompt, and a login within
60 s of a killed client (the server still holds the character linkdead).

If another DAoC server is already using port 10300, stop it first.

### Stopping

All of these act only on this checkout's install, never on another checkout's.

- `daoc client stop` — stops the client, then waits until the server has
  dropped the linkdead character so the next login is not refused.
- `daoc client kill` — tears down the launcher loop, wine tree and x87sidecar of
  this install at once and waits for its wineserver to exit.
- `daoc server stop` — saves and stops the server; `daoc server status` prints
  `running (pid N)` or `stopped`.

Launcher overrides (set in the environment; `daoc client start` forwards them):
`DAOC_WINE_HOME` (wine tree, default `dist/wine`), `DAOC_WINEPREFIX`
(default `dist/prefix`), `DAOC_DLL_OVERRIDES` (replaces `d3d9,dxgi=b`),
`WINE_COMPATDB` (renderer choice, e.g.
`$'v=5\nname=daoc;exe=game.dll;d3d9=wined3d'` for wined3d instead of mtld3d).

### Performance and the FPS overlay

The 1.127 client does its 3D math with x87 floating point, which Rosetta 2
emulates slowly: under plain Wine the game thread is CPU-bound at about 7 FPS.
The bundled x87sidecar translates that code to native ARM64 and mtld3d renders
on Metal; together they run the client at 90–105 FPS average in the benchmark
below (vsync off, uncapped).

To show Apple's Metal Performance HUD (FPS and a frame-time graph, top right of
the game window), launch with `DAOC_FPS_OVERLAY=1`:

```bash
DAOC_FPS_OVERLAY=1 daoc client start
```

### Benchmark

`daoc client bench [--seconds 300] [--tag bench]` is the performance gate. It
logs in as the saved Game account's most recently played character
(`DAOC_CHARACTER` picks another), plays for 5 minutes (NPC interaction plus
movement through the Connacht town), and reports average FPS, p95/p99 frame
time and 1%-low FPS from a per-present probe. It passes (exit 0) at an average
of at least 60 FPS with p95 at or under 16.7 ms; exit 1 is a fail, exit 2 an
invalid run (no frames, server gone, character never moved). It raises the
account to GM for the run (it needs `/jump` and `/target`) and puts it back
afterwards; if that restore fails, the next run does it first. Run it from a GUI
Terminal with the server up (`daoc server start`); it uses the same port as
`daoc client start` and needs `brew install mingw-w64` for its input helper.

## Admin and saved progress

`daoc admin` opens the running server's admin screen; `daoc admin <command>`
runs one command (`daoc admin --help` lists them: accounts, bots, population,
options, ...). `daoc progress` runs the saved-progress tools described under
Update. Both pass their arguments through unchanged.

## Graphics (optional)

`daoc graphics` lets you pick which optional graphical patches from
[OfflineDAoC-macOS-graphics](https://github.com/trozzelle/OfflineDAoC-macOS-graphics)
are on for this install's client. Nothing is fetched until you run it: the first
call clones the commit pinned for the Graphics project into
`upstream/graphics/`. Quit the client first; changes take effect at the next
launch.

Run it with no arguments for a checklist: toggle patches by number, press Enter
to apply. Only the patches you toggled change.

```
  1. [x] Native resolution (Wine Retina mode)
  2. [ ] Colour-managed output (sRGB)
  3. [ ] Texture pack  (not installed)
  4. [ ] Anisotropic filtering
Toggle by number (e.g. 1 3), Enter to apply, q to quit:
```

Turning anisotropic filtering on asks for its level (2x, 4x, 8x or 16x; Enter
keeps the current one, 16x the first time).

| Patch | On | Off |
|---|---|---|
| `retina` | Wine's Retina mode: the client renders at the panel's physical resolution (3840x2160 on a 4K panel instead of 1920x1080 upscaled by macOS); the interface looks half as large | The prefix's Retina setting from before |
| `srgb` | `color.space = accurate` in `mtld3d.conf`: colour-managed sRGB output instead of the panel's native gamut | The setting removed |
| `textures` | A texture pack you downloaded (for example [Sqeak's DAoC Textures](https://www.nexusmods.com/darkageofcamelot/mods/2), whose installer is Windows-only) over the client's folders; the first time, it asks for the archives | Original files back, the pack kept aside (APFS clones) |
| `anisotropy` | Anisotropic filtering at 2x, 4x, 8x or 16x: a small `d3d9.dll` next to `game.dll`, and the installed `dist/DAoCLauncher.app` set to load it (`d3d9=n,b`); ground, roads and walls stay sharp at a distance. After `daoc client install` copies a fresh launcher it shows `partly on`; enable it again | Proxy removed, the launcher's line back as it was |

Without the checklist, for scripts:

```bash
daoc graphics status                       # each patch and whether it is on
daoc graphics enable retina srgb
daoc graphics enable anisotropy --level 8  # or 2, 4, 16; changes the level while on
daoc graphics enable textures --archives ~/Downloads/Sqeaks-DAoC-Textures-v0.1-Part{1,2}.7z
daoc graphics disable textures
daoc graphics textures uninstall           # delete the pack files for good
```

The [Graphics project's README](https://github.com/trozzelle/OfflineDAoC-macOS-graphics#readme)
lists every command and how each change is recorded and undone.

## Update

Each part has its own update:

```bash
daoc server update --check     # report what moved upstream; change nothing
daoc server update             # move the server to the upstream's latest commit and rebuild
daoc client update             # move the client to the latest OfflineDAoC release
daoc graphics update           # move the Graphics project to its latest commit
```

`--check` works on all three. The versions this repo was tested with are its
Shipped pins, in `manifest.json`. An update records your newer version as a
Local pin in `.daoc/pins.json` (not tracked by git), so it applies only to this
checkout. When a `git pull` brings a new Shipped pin for that part, your Local
pin lapses and the shipped version applies again. `daoc` shows both pins, what
each install was built from, and "rebuild due" when they differ: `daoc server
install` or `daoc client install` brings that install to the pin (the client
keeps your graphics patches, as an update does).

`daoc server update` checks the macOS patches still apply before it moves
anything. If the server is running it asks before stopping it. The rebuild
replaces only the program files, so your `config/`, `data/` (accounts,
characters, bots), `logs/` and `navmesh/` stay in place.

`daoc client update` re-applies the Client patch to the new `game.dll`. If that
`game.dll` is one it doesn't know, it stops with "not a Proven build; it needs a
shipped update" and leaves your client as it was. Graphics patches you had on
are carried across to the new client.

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

To bring progress from elsewhere (an older server folder, or a Windows Offline
DAoC folder containing `runtime/`), use
`daoc progress import <folder> --replace-progress`. It replaces this server's
progress and only reads the source. `daoc progress inspect <folder>` shows what
a save holds without changing anything. Undo steps and details are in
`server/README.md` (Maintenance).

Maintainers: `daoc dev ship-pins` writes the effective pins into
`manifest.json` as the new Shipped pins, and `daoc dev e2e` runs the end-to-end
check on its own server on ports 20300/20400, putting the config back when it's
done.

## Commands that changed name

| Old | New |
|---|---|
| `./install-server.sh [--verbose]` | `daoc server install [--verbose]` |
| `cd server/dist/daoc-server && ./daoc-server.sh start\|stop\|status` | `daoc server start\|stop\|status` |
| `(cd server/dist/daoc-server && ./daoc-admin …)` | `daoc admin …` |
| `./daoc-progress upgrade\|import\|inspect …` | `daoc progress …` |
| `./install-client.sh [--verbose]` | `daoc client install [--verbose]` |
| `open -n dist/DAoCLauncher.app --args wine game.dll …` / `client/tools/launch-client.sh [N]` | `daoc client start [--retries N]` |
| `launch-client.sh --credentials` / `--character` | `daoc client login` / `daoc client start --dry-run` |
| `client/tools/stop-client.sh` / `kill-client.sh` | `daoc client stop` / `daoc client kill` |
| `client/bench-run.sh [s] [tag]` | `daoc client bench --seconds s --tag tag` |
| `./graphics.sh …` | `daoc graphics …` |
| `./update.sh check` | `daoc server\|client\|graphics update --check` |
| `./update.sh server\|client\|graphics` | `daoc server\|client\|graphics update` (Local pin); `daoc dev ship-pins` (manifest) |
| `./e2e-test.sh [a] [p]` | `daoc dev e2e [a] [p]` |

For one release, `install-server.sh`, `install-client.sh`, `update.sh`,
`graphics.sh` and `e2e-test.sh` remain as stubs that print
`renamed: use daoc …` and exit 2.

## Docs

- `docs/DESIGN.md` — repo layout, manifest schema, install flows, server updates
  and saved progress
- `docs/REVIEW.md` — review of the ported code and scripts
- `docs/CLIENT-NOTES.md` — client findings under Wine on Apple silicon (x87
  performance, privacy prompt, prefix user, linkdead wait)
- `docs/SERVER-NOTES.md` — upstream server issues documented, not patched