# daoc-macos

Dark Age of Camelot, offline, on a Mac. Apple Silicon (arm64) with Rosetta 2;
needs Xcode Command Line Tools and cmake (`brew install cmake`) — everything
else is fetched.

DAoC is © Mythic Entertainment / Broadsword Online Games (Electronic Arts).
This is unaffiliated fan tooling; the original client and game data remain
their property.

Nothing here would exist without the upstream projects — go support them:

- [OpenDAoC](https://github.com/OpenDAoC/OpenDAoC-Core) — the open DAoC server emulator
- [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC) — the playable offline
  bundle built on OpenDAoC; it ships the original 1.127 Windows client, which the
  client install downloads
- [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots) —
  a pinned OpenDAoC fork (Offline DAoC 0.33) that the server install builds on
- [Gcenx](https://github.com/Gcenx/macOS_Wine_builds) — the macOS Wine Staging
  builds the client runs under

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

Downloads the OfflineDAoC release (≈5 GB), installs Wine Staging 11.18, patches
`game.dll`, and sets up a wine prefix.

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

The client's GL init under Rosetta is flaky — if it crashes before the splash,
relaunch. Login takes 1–2 minutes. Exit with `/quit` in chat.

If another DAoC server is already using port 10300, stop it first.
`./e2e-test.sh` runs its own server on 20300/20400 and puts the config back
when it's done.

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