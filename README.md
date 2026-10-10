# daoc-macos

Dark Age of Camelot, offline, on a Mac.

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

This repo only adds install scaffolding and macOS compatibility patches.
Server-side patches are GPL v3, like the upstream they modify.

## What it does

Two independent installs from one checkout:

- `server-install` — fetches the pinned linux server upstream, applies the macOS
  port patches, builds a runnable server.
- `client-install` — fetches the pinned OfflineDAoC release (includes the original
  Windows client), installs Wine, and applies the client patches that let it talk
  to a local server.

A manifest pins exact upstream versions and hashes, so installs are reproducible.
An `update` command bumps the pins when upstream moves.

## Install the server

```bash
./install-server.sh
```

Clones the pinned upstream, pre-checks the macOS patches, builds
`server/dist/daoc-server/`. Needs Xcode CLT, cmake, and the .NET 10 SDK
(installed automatically). Then:

```bash
cd server/dist/daoc-server
./daoc-server.sh start
```

## Install the client

```bash
./install-client.sh
```

Fetches the pinned OfflineDAoC release (≈5 GB, verified per-part and as a whole
against the release's own manifest), installs Wine Staging 11.18, patches
`game.dll` (byte-verified against the pinned pristine hash), and initializes a
win10-mode prefix.

## Play

With the server running:

```bash
open -n dist/DAoCLauncher.app --args wine game.dll 127.0.0.1 10300 42 <account> <password>
```

Create the account first (`daoc-admin accounts create <name> <pass>` in
`server/dist/daoc-server/`) — the login packet carries the credentials in plain
text, so the stored hash must match what you type. The client's wined3d GL init
under Rosetta is flaky (~half of launches crash before the splash); kill it and
relaunch. Login takes 1–2 minutes. Exit with `/quit` in chat.

## Update

```bash
./update.sh check    # report what moved upstream
./update.sh server   # bump the server pin (patches are re-checked first)
./update.sh client   # bump the client pin (game.dll hash re-derivation is manual)
```

## Docs

- `docs/DESIGN.md` — repo layout, manifest schema, install flows
- `docs/REVIEW.md` — review of the ported code and scripts
- `docs/SERVER-NOTES.md` — upstream server issues documented, not patched