# OfflineDAoC for macOS

> **Disclaimer.** Dark Age of Camelot is the property of Mythic Entertainment /
> Broadsword Online Games (Electronic Arts). This is unaffiliated fan tooling; the
> original client and game data remain their property.

Run the [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC) server and game
client on Apple Silicon: the server builds natively for arm64, the original
1.127 Windows client runs under Wine, by default an x86_64 Wine under Rosetta 2;
`daoc client install --wine arm64` uses an arm64 Wine with FEX instead, which needs
no Rosetta (opt-in, see [docs/PLAY.md](docs/PLAY.md#arm64-wine-no-rosetta)).

<p align="center">
<img width="564" height="381" alt="A screenshot of a troll fighting a lync in Dark Age of Camelot" src="https://github.com/user-attachments/assets/112a2ca1-3f2c-48ea-9b6b-fe97f553b535" /></p>

## Built on

This repo only adds install scaffolding and macOS compatibility patches. Go
support the upstream projects:

- [OpenDAoC](https://github.com/OpenDAoC/OpenDAoC-Core): the open DAoC server emulator
- [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC): the offline bundle
  built on OpenDAoC, and the source of the client
- [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots):
  the pinned OpenDAoC fork (Offline DAoC 0.35) the server builds from
- [athei/wine-build](https://github.com/athei/wine-build): the CrossOver-based
  macOS Wine, with [x87sidecar](https://github.com/athei/x87sidecar) (fast x87
  math on ARM64) and [mtld3d](https://github.com/athei/mtld3d) (Direct3D 9 on Metal)
- [Hadron](https://github.com/Broyojo/hadron): the arm64 Wine behind `--wine arm64`,
  with [FEX](https://github.com/FEX-Emu/FEX) (x86 emulation, including the client's
  x87 math) and mtld3d

## Requirements

- A Mac with Apple Silicon running macOS 26 or later, and Rosetta 2 (or, for
  `--wine arm64`, macOS 27 or later and no Rosetta)
- Xcode Command Line Tools (`xcode-select --install`)
- cmake (`brew install cmake`)
- An internet connection for the ≈5 GB client download

Everything else is fetched.

## Quick start

<!-- x-release-please-start-version -->
```bash
git clone --branch v0.1.1 <this repo> daoc-macos && cd daoc-macos
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
