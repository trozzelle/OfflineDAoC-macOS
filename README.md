# OfflineDAoC for macOS

> **Disclaimer.** Dark Age of Camelot is the property of Mythic Entertainment /
> Broadsword Online Games (Electronic Arts). This is unaffiliated fan tooling; the
> original client and game data remain their property.

Run the [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC) server and game
clients on Apple Silicon. Choose the game, 0.35, 0.36 or 0.37, with the Sluaghbinder
(`0.35b`, `0.36b`, `0.37b`) or the classic classes only (`0.35`, `0.36`, `0.37`). The
server builds natively for arm64. The original 1.127 Windows client runs under Wine, by
default an x86_64 Wine under Rosetta 2, or an arm64 Wine with FEX instead, which needs
no Rosetta (opt-in, see [docs/PLAY.md](docs/PLAY.md#arm64-wine-no-rosetta)). From 0.36,
upstream's new Godot client runs natively too, beside the original one.

<p align="center">
<img width="564" height="381" alt="A screenshot of a troll fighting a lync in Dark Age of Camelot" src="https://github.com/user-attachments/assets/112a2ca1-3f2c-48ea-9b6b-fe97f553b535" /></p>

## Built on

This repo adds install scaffolding and macOS compatibility; the server's macOS
changes live in its own repo. Go support the upstream projects:

- [OpenDAoC](https://github.com/OpenDAoC/OpenDAoC-Core): the open DAoC server emulator
- [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC): the offline bundle
  built on OpenDAoC, and the source of the client
- [OfflineDAoC-macOS-server](https://github.com/trozzelle/OfflineDAoC-macOS-server):
  the server the build uses: Offline DAoC's server code, world data and navmeshes,
  with its admin host, synced to each Offline DAoC version, plus the macOS fixes. It
  started as a fork of catastrophic-impact's
  [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots)
- [athei/wine-build](https://github.com/athei/wine-build): the CrossOver-based
  macOS Wine, with [x87sidecar](https://github.com/athei/x87sidecar) (fast x87
  math on ARM64) and [mtld3d](https://github.com/athei/mtld3d) (Direct3D 9 on Metal)
- [Hadron](https://github.com/Broyojo/hadron): the arm64 Wine behind `--wine arm64`,
  with [FEX](https://github.com/FEX-Emu/FEX) (x86 emulation, including the client's
  x87 math) and mtld3d
- [Godot](https://godotengine.org): the engine of upstream's new client, run with its
  official macOS .NET build

## Requirements

- A Mac with Apple Silicon running macOS 26 or later, and Rosetta 2 (or, for
  `--wine arm64`, macOS 27 or later and no Rosetta)
- Xcode Command Line Tools (`xcode-select --install`)
- cmake (`brew install cmake`)
- An internet connection for the ≈5 GB client download (the new client: about
  30 GB more, 34 GB installed)

Everything else is fetched.

## Quick start

<!-- x-release-please-start-version -->
```bash
git clone --branch v0.3.0 <this repo> daoc-macos && cd daoc-macos
./daoc self-install      # puts `daoc` in ~/.local/bin

daoc server install      # build the server
daoc client install      # download the client and Wine, set up the prefix
daoc server start        # holds this terminal with the admin screen
```
<!-- x-release-please-end -->

That clones the latest release. Each release is a git tag with its changes in
[CHANGELOG.md](CHANGELOG.md); `daoc` says when a newer one is out, and
[docs/UPDATING.md](docs/UPDATING.md#daoc-itself) moves you to it.

In a **second terminal**:

```bash
daoc admin accounts create <name> <pass>
daoc client login        # save the account in the login Keychain
daoc client start        # launch into the world
```

Exit with `/quit` in chat; stop with `daoc client stop` and `daoc server stop`.
Run `daoc` with no arguments for an overview of your installs.

## Choosing the game and the client

A checkout starts as `0.35b` with the original client. To move it, server, save
and clients together:

```bash
daoc game                         # the games and which one is selected
daoc game switch 0.37b            # 0.35, 0.35b, 0.36, 0.36b, 0.37 or 0.37b
daoc client install --client new  # 0.36 and later: the new client (about 34 GB; 0.37: 36 GB), now the default
daoc client start                 # the default client; --client original|new picks one
```

Your progress moves with the switch; the previous save is backed up first. Going
back to an older version needs a backup made under it
([docs/UPDATING.md](docs/UPDATING.md#switching-games)). Both clients play the same
account and characters, one at a time.

**Original Client**

<img width="3450" height="2232" alt="CleanShot 2026-10-18 at 12 10 16 PM@2x" src="https://github.com/user-attachments/assets/c7dbfb1e-fad5-4ba5-b00a-9aec5ab0c444" />

**Godot Client**

<img width="3452" height="2232" alt="CleanShot 2026-10-18 at 12 13 19 PM@2x" src="https://github.com/user-attachments/assets/235c7bd4-38f9-4899-8cce-d8aa989fa69b" />

## Without Rosetta: the arm64 Wine

Apple keeps Rosetta 2 fully working only through macOS 27. On macOS 27 or later
you can already run the client without it:

```bash
daoc client install --wine arm64     # Hadron's arm64 Wine, next to the default one
daoc client start
```

- It's opt-in while it is being measured; `daoc client install --wine rosetta`
  switches back, and both installs are kept.
- On first start macOS asks whether "wine" may use the local network. Allow it,
  or every start waits ~35 s (System Settings > Privacy & Security > Local Network).
- `daoc` runs it with FEX's reduced-precision x87 (`FEX_X87REDUCEDPRECISION=1`):
  about 120 FPS in world, against ~10–15 FPS at FEX's default full precision.

Details: [docs/PLAY.md](docs/PLAY.md#arm64-wine-no-rosetta).

## Documentation

**Playing**

- [docs/PLAY.md](docs/PLAY.md): full walkthrough, playing over SSH, performance,
  troubleshooting
- [docs/GRAPHICS.md](docs/GRAPHICS.md): optional graphics patches (Retina, sRGB,
  texture packs, anisotropic filtering)
- [docs/UPDATING.md](docs/UPDATING.md): new releases, updates, pins, and moving
  or importing saved progress
- [docs/QUICK-COMMANDS.md](docs/QUICK-COMMANDS.md): every command, and the old
  script names they replace

**Developing**

- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): tests, benchmark gate, maintainer
  commands, and the design and research notes

## License

Server-side patches are GPL v3, like the upstream they modify. See [LICENSE](LICENSE).
