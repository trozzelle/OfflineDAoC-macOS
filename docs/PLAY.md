# Playing on macOS

The full walkthrough: setting up the `daoc` command, installing the server and
client, playing, stopping, and what to do when something goes wrong. The
[README](../README.md) has the short version.

- [Set up the `daoc` command](#set-up-the-daoc-command)
- [Install the server](#install-the-server)
- [Install the client](#install-the-client)
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
git clone --branch v0.1.1 <this repo> daoc-macos && cd daoc-macos
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

Run `daoc` with no arguments for an overview: where the checkout is, whether the
Server install and Client install are present, whether the server runs, each
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
`daoc client start` asks for it the first time.

`daoc client start`:

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

- `daoc client stop` — stops the client, then waits until the server has
  dropped the linkdead character so the next login is not refused.
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
[benchmark](DEVELOPMENT.md#benchmark) (vsync off, uncapped).

To show Apple's Metal Performance HUD (FPS and a frame-time graph, top right of
the game window), launch with `DAOC_FPS_OVERLAY=1`:

```bash
DAOC_FPS_OVERLAY=1 daoc client start
```

## Launcher overrides

Set in the environment; `daoc client start` forwards them.

| Variable | Default | Effect |
|---|---|---|
| `DAOC_WINE_HOME` | `dist/wine` | Wine tree |
| `DAOC_WINEPREFIX` | `dist/prefix` | Wine prefix |
| `DAOC_DLL_OVERRIDES` | `d3d9,dxgi=b` | Replaces the DLL overrides |
| `WINE_COMPATDB` | — | Renderer choice, e.g. `$'v=5\nname=daoc;exe=game.dll;d3d9=wined3d'` for wined3d instead of mtld3d |

## Troubleshooting

- **The client crashes before the splash.** The launcher relaunches it on its own
  (up to 10 tries; each attempt is traced to `/tmp/daoc-launcher.log`).
- **No login screen after ~3 minutes.** Note what is on screen and check
  `tail -50 /tmp/daoc-wine.log`.
- **The client sits without logging in.** Two known causes, described in
  [CLIENT-NOTES.md](CLIENT-NOTES.md): an unanswered macOS privacy prompt, and a
  login within 60 s of a killed client (the server still holds the character
  linkdead).
- **Port in use.** If another DAoC server is already using port 10300, stop it
  first.
