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
  client install downloads
- [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots) —
  a pinned OpenDAoC fork (Offline DAoC 0.33) that the server install builds on
- [athei/wine-build](https://github.com/athei/wine-build) — the CrossOver-based
  macOS Wine the client runs under, with
  [x87sidecar](https://github.com/athei/x87sidecar) (native ARM64 for the
  client's x87 floating point, which Rosetta otherwise emulates slowly) and
  [mtld3d](https://github.com/athei/mtld3d) (Direct3D 9 on Metal)

This repo only adds install scaffolding and macOS compatibility patches.
Server-side patches are GPL v3, like the upstream they modify.

## Install the server

```bash
./install-server.sh
```

Clones the pinned upstream, checks the macOS patches apply, builds
`server/dist/daoc-server/`. Then:

```bash
cd server/dist/daoc-server
./daoc-server.sh start
```

## Install the client

```bash
./install-client.sh
```

Downloads the OfflineDAoC release (≈5 GB) and athei's CrossOver Wine build,
patches `game.dll`, and sets up a wine prefix. The prefix keeps its Windows
profile folders (Documents, Desktop, ...) inside the prefix, so the client never
triggers a macOS privacy prompt for your home folders.

## Play

Start the server (it holds the terminal with the admin screen):

```bash
cd server/dist/daoc-server
./daoc-server.sh start
```

In a **second terminal**, from the repo root, create an account and launch the
client:

```bash
(cd server/dist/daoc-server && ./daoc-admin accounts create <name> <pass>)
open -n dist/DAoCLauncher.app --args wine game.dll 127.0.0.1 10300 42 <name> <pass>
```

If the client crashes before the splash, the launcher relaunches it on its own
(up to 10 tries; each attempt is traced to `/tmp/daoc-launcher.log`). Exit with
`/quit` in chat. If the client runs longer than ~3 minutes with no login
screen, note what is on screen and check `tail -50 /tmp/daoc-wine.log` —
a live client that never connects is a known open issue (see
`HANDOFF.md`).

If another DAoC server is already using port 10300, stop it first.
`./e2e-test.sh` runs its own server on 20300/20400 and puts the config back
when it's done.

### Performance and the FPS overlay

The 1.127 client does its 3D math with x87 floating point, which Rosetta 2
emulates slowly: under plain Wine the game thread is CPU-bound at about 7 FPS.
The bundled x87sidecar translates that code to native ARM64 and mtld3d renders
on Metal; together they run the client at 90–105 FPS average in the benchmark
below (vsync off, uncapped).

To show Apple's Metal Performance HUD (FPS and a frame-time graph, top right of
the game window), launch with `DAOC_FPS_OVERLAY=1`:

```bash
open -n dist/DAoCLauncher.app --env DAOC_FPS_OVERLAY=1 --args wine game.dll 127.0.0.1 10300 42 <name> <pass>
```

### Benchmark

`client/bench-run.sh [seconds] [tag]` is the performance gate. The first run (and
the first `client/tools/launch-client.sh`) asks for your game account and saves it
in the login Keychain. The bench logs in as the account's most recently played
character (`DAOC_CHARACTER` to pick another of its characters), plays for
5 minutes (NPC interaction plus movement through the Connacht town), and reports
average FPS, p95/p99 frame time and 1%-low FPS from a per-present probe. It passes
at an average of at least 60 FPS with p95 at or under 16.7 ms. Run it from a GUI
Terminal with the server up (`./daoc-server.sh start`); the client connects to the
`<Port>` in the server's `config/serverconfig.xml` (10300 by default; set
`DAOC_PORT` to override). It needs `brew install mingw-w64` for its input helper.

## Update

```bash
./update.sh check    # report what moved upstream
./update.sh server   # bump the server pin (patches are re-checked first)
./update.sh client   # bump the client pin
```

## Docs

- `docs/DESIGN.md` — repo layout, manifest schema, install flows
- `docs/REVIEW.md` — review of the ported code and scripts
- `docs/SERVER-NOTES.md` — upstream server issues documented, not patched