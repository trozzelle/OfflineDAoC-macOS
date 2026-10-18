# Playing on macOS

The full walkthrough: setting up the `daoc` command, installing the server and
client, playing, stopping, and what to do when something goes wrong. The
[README](../README.md) has the short version.

- [Set up the `daoc` command](#set-up-the-daoc-command)
- [Install the server](#install-the-server)
- [Install the client](#install-the-client)
- [Choose the game](#choose-the-game)
- [The new client](#the-new-client)
- [Play](#play)
- [Playing over SSH](#playing-over-ssh)
- [Stopping](#stopping)
- [Admin](#admin)
- [Performance and the FPS overlay](#performance-and-the-fps-overlay)
- [Launcher overrides](#launcher-overrides)
- [Troubleshooting](#troubleshooting)

## Set up the `daoc` command

<!-- x-release-please-start-version -->
```bash
git clone --branch v0.3.0 <this repo> daoc-macos && cd daoc-macos
./daoc self-install
```
<!-- x-release-please-end -->

That is the latest release; [UPDATING.md](UPDATING.md#daoc-itself) moves the
checkout to a newer one.

`self-install` writes `~/.local/bin/daoc`, a small wrapper that runs this
checkout's `./daoc`. If `~/.local/bin` is not on your PATH it offers to add this
line to `~/.zprofile` (default no), or you add it yourself:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Run `daoc` with no arguments for an overview: where the checkout is, the
selected game and default client, which game each client install and the save
belong to (with the switch that fixes a mismatch), whether the server runs, each
pin, and whether a newer release is out. `daoc --version` prints the release
you run. `daoc <group> --help` lists a group's actions. `admin`, `progress` and
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

Downloads the selected game's OfflineDAoC release (≈5 GB) and athei's CrossOver Wine build,
applies the Client patch to `game.dll`, and sets up a wine prefix. Re-runs skip
finished steps. The prefix keeps its Windows profile folders (Documents,
Desktop, ...) inside the prefix, so the client never triggers a macOS privacy
prompt for your home folders. Add `--verbose` to see the Wine download's
progress bar and wine's prefix setup logging.

### arm64 Wine (no Rosetta)

```bash
daoc client install --wine arm64
```

Installs [Hadron](https://github.com/Broyojo/hadron)'s arm64 Wine instead: Wine
built for Apple Silicon, with FEX translating the 32-bit client's x86 code and
mtld3d rendering on Metal. It needs macOS 27 or later and no Rosetta 2, which
Apple stops shipping in full after macOS 27. It is opt-in while it is being
measured against the default.

- It lives next to the default Wine (`dist/wine-arm64`, `dist/prefix-arm64`), and
  its prefix gets your client settings copied over from the default one.
- The last `daoc client install` decides which one `daoc client start`, `stop`,
  `kill`, `bench` and `daoc graphics` use (recorded in `dist/.wine-flavour`).
  Switch back with `daoc client install --wine rosetta`; each switch keeps the
  other Wine and its prefix. Re-apply Retina mode (`daoc graphics`) after a
  switch: it is a setting of each prefix.
- **Allow its Local Network access.** On its first start macOS asks whether
  "wine" may find devices on your local network. Until you allow it, every client
  start waits about 35 s while Wine looks up the Mac's own name. If you missed
  or denied the prompt, turn "wine" on in System Settings > Privacy & Security >
  Local Network; `daoc client install --wine arm64` says when it is still held.

## Choose the game

| Game | Version | Classes | Clients |
|---|---|---|---|
| `0.35` | 0.35 | classic classes only | original |
| `0.35b` | 0.35 | with the Sluaghbinder | original |
| `0.36` | 0.36 | classic classes only | original, new |
| `0.36b` | 0.36 | with the Sluaghbinder | original, new |

`daoc game` lists them and marks the selected one; a checkout starts as `0.35b`.

```bash
daoc game switch 0.36b
```

The switch checks everything it can first and changes nothing when it refuses:
a save with Sluaghbinder characters cannot move into a classic-classes game, and
Sluaghbinder bots move only with `--leave-sluaghbinder-bots` (they are left
behind). Then it downloads what is new, stops the client and (after asking) the
server, rebuilds the server when the version changes, moves your save into the
game's world (backed up first), and brings each installed client along. If it
is interrupted, `daoc` says so; run the same switch again to finish it.

Both editions of a version come from one download, so switching between `0.36`
and `0.36b` downloads nothing and swaps only `game.dll`.

## The new client

From 0.36, upstream ships a second client built in Godot 4. daoc runs it natively
with the official macOS Godot, so it needs neither Wine nor Rosetta:

```bash
daoc client install --client new   # about 30 GB, 34 GB installed; it becomes the default client
daoc client start                  # or: daoc client start --client new
```

- The download comes in 19 parts; each one is checked, unpacked and deleted
  before the next, so the install needs about 36 GB free while it runs. If it is
  interrupted, run it again and it continues.
- It always connects to port 10300 (it has no port setting), so the server must
  run on 10300.
- `daoc client start` waits until the server accepts the login. The client then
  shows realm select; pick or create the character there (`--character` is for the
  original client only).
- `daoc client install --client original` makes the original client the default
  again; both stay installed and play the same account and characters, one at a
  time.
- Its settings (graphics presets, key bindings) live in
  `~/Library/Application Support/Godot/app_userdata/MMOEngine`, shared by every
  checkout. `daoc` never deletes that folder.
- Graphics patches and `daoc client bench` apply to the original client only.

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
`daoc client start` asks for it the first time.

`daoc client start` starts the default client; `--client original|new` picks one
for this start. The original client:

- logs in as `DAOC_CHARACTER` (or `--character NAME`), else the account's most
  recently played character (read from the server database; `--dry-run` prints
  it and exits);
- connects to the `<Port>` in the server's `config/serverconfig.xml`
  (`DAOC_PORT` overrides);
- relaunches a client that hangs before entering the world (`--retries N`,
  default 3).

An account with no character yet is logged in to character select instead,
where you create one; the next `daoc client start` enters the world with it.

Exit the game with `/quit` in chat.

## Playing over SSH

Over SSH, the login Keychain is locked for that session even while you are
logged in at the Mac, because macOS unlocks it only for the session you logged
in to. `daoc client login`, `client start` and `client bench` then run
`security unlock-keychain`, which asks for your macOS login password. Without a
terminal (a script, `ssh host daoc …` with no `-t`), they stop and tell you to run
`security unlock-keychain` first. The client still opens on the Mac's own screen,
so someone has to be logged in there.

## Stopping

All of these act only on this checkout's install, never on another checkout's.

- `daoc client stop` — stops the client (either one), then waits until the server
  has dropped the linkdead character so the next login is not refused.
- `daoc client kill` — tears down the launcher loop, wine tree and x87sidecar of
  this install at once and waits for its wineserver to exit.
- `daoc server stop` — saves and stops the server; `daoc server status` prints
  `running (pid N)` or `stopped`.

## Admin

`daoc admin` opens the running server's admin screen; `daoc admin <command>`
runs one command (`daoc admin --help` lists them: accounts, bots, population,
options, ...). `daoc progress` runs the saved-progress tools described in
[UPDATING.md](UPDATING.md). Both pass their arguments through unchanged.

## Performance and the FPS overlay

The 1.127 client does its 3D math with x87 floating point, which Rosetta 2
emulates slowly: under plain Wine the game thread is CPU-bound at about 7 FPS.
The bundled x87sidecar translates that code to native ARM64 and mtld3d renders
on Metal; together they run the client at 90–105 FPS average in the
[benchmark](DEVELOPMENT.md#benchmark) (vsync off, uncapped). The arm64 Wine
translates it with FEX instead, which does x87 at full 80-bit precision in
software unless told otherwise: in world that is ~10–15 FPS. `daoc` therefore
runs it with `FEX_X87REDUCEDPRECISION=1` (x87 as 64-bit doubles), which gives
~120 FPS in world; the benchmark gate has not been run on it yet.

To show Apple's Metal Performance HUD (FPS and a frame-time graph, top right of
the game window), launch with `DAOC_FPS_OVERLAY=1`:

```bash
DAOC_FPS_OVERLAY=1 daoc client start
```

## Launcher overrides

Set in the environment; `daoc client start` forwards them.

| Variable | Default | Effect |
|---|---|---|
| `DAOC_WINE_HOME` | `dist/wine` (`dist/wine-arm64` with `--wine arm64`) | Wine tree |
| `DAOC_WINEPREFIX` | `dist/prefix` (`dist/prefix-arm64`) | Wine prefix |
| `DAOC_DLL_OVERRIDES` | `d3d9,dxgi=b` (arm64: `mscoree,mshtml=;d3d9=n,b`) | Replaces the DLL overrides |
| `WINE_COMPATDB` | — | Rosetta Wine: renderer choice, e.g. `$'v=5\nname=daoc;exe=game.dll;d3d9=wined3d'` for wined3d instead of mtld3d |
| `MTLD3D_*`, `FEX_*` | arm64: `MTLD3D_CONFIG=color.hdr.enable=false;present.vsync=off`, `MTLD3D_NO_CRASH_HANDLER=1`, `FEX_DISKCACHE=1`, `FEX_X87REDUCEDPRECISION=1` | mtld3d and FEX settings; `FEX_X87REDUCEDPRECISION=0` brings back full x87 precision (and ~10–15 FPS) |
| `WINE_LARGE_ADDRESS_AWARE` | arm64: `1` | 4 GB address space for the 32-bit client |

## Troubleshooting

- **The client crashes before the splash.** The launcher relaunches it on its own
  (up to 10 tries; each attempt is traced to `/tmp/daoc-launcher.log`).
- **No login screen after ~3 minutes.** Note what is on screen and check
  `tail -50 /tmp/daoc-wine.log`.
- **The client sits without logging in.** Two known causes, described in
  [CLIENT-NOTES.md](CLIENT-NOTES.md): an unanswered macOS privacy prompt, and a
  login within 60 s of a killed client (the server still holds the character
  linkdead).
- **arm64 Wine: ~10–15 FPS in world.** `daoc` runs it with
  `FEX_X87REDUCEDPRECISION=1`; check that your environment does not set it to `0`
  (see [Performance](#performance-and-the-fps-overlay)). Without it FEX emulates
  the client's x87 math at full precision in software.
- **arm64 Wine: every start takes ~35 s longer.** macOS is holding its Local
  Network access; allow "wine" in System Settings > Privacy & Security > Local
  Network ([arm64 Wine](#arm64-wine-no-rosetta)).
- **Port in use.** If another DAoC server is already using port 10300, stop it
  first.
- **The new client sits with no window.** It was started outside the Mac's GUI
  session; `daoc client start` uses `open`, so someone has to be logged in at the
  Mac. Its output is in `/tmp/daoc-new-client.log`.
- **The new client refuses to start with another port.** It only connects to
  10300; set `<Port>` back in the server's `config/serverconfig.xml` (or unset
  `DAOC_PORT`).
