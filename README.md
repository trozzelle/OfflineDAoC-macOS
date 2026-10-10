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

## Status

Work in progress. Docs land in `docs/`.