# daoc-macos

> **Disclaimer.** Dark Age of Camelot is the property of Mythic Entertainment /
> Broadsword Online Games (Electronic Arts). This is unaffiliated fan tooling; the
> original client and game data remain their property.

Run the [OfflineDAoC](https://github.com/shadowofze/OfflineDAoC) server and game
client on an Apple Silicon Mac: the server builds natively for arm64, the original
1.127 Windows client runs under Wine with Rosetta 2. The `daoc` command installs,
runs and updates both.

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

## Requirements

- A Mac with Apple Silicon and Rosetta 2
- Xcode Command Line Tools (`xcode-select --install`)
- cmake (`brew install cmake`)
- An internet connection for the ≈5 GB client download

Everything else is fetched.

## Quick start

<!-- x-release-please-start-version -->
```bash
git clone --branch v0.1.0 <this repo> daoc-macos && cd daoc-macos
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
