# Quick commands

Every `daoc` action at a glance. `daoc <group> --help` has the details.

| Command | What it does |
|---|---|
| `daoc` | Overview: checkout, installs, server state, pins |
| `daoc self-install` | Write the `~/.local/bin/daoc` wrapper for this checkout |
| `daoc server install [--verbose]` | Build `server/dist/daoc-server` from the pinned upstream |
| `daoc server start` | Start the server (holds the terminal with the admin screen) |
| `daoc server stop` | Save and stop the server |
| `daoc server status` | Print `running (pid N)` or `stopped` |
| `daoc server update [--check]` | Move the server to its upstream's latest commit and rebuild |
| `daoc client install [--verbose]` | Install Wine, the client, the Client patch and the Wine prefix |
| `daoc client login` | Save or replace the Game account in the Keychain |
| `daoc client start [--character NAME] [--retries N] [--dry-run]` | Launch the client into the world |
| `daoc client stop` | Stop the client and wait out Linkdead |
| `daoc client kill` | Tear the client down at once |
| `daoc client update [--check]` | Move the client to the latest OfflineDAoC release |
| `daoc client bench [--seconds S] [--tag T]` | Performance gate (exit 0 pass, 1 fail, 2 invalid) |
| `daoc admin [command …]` | Admin screen, or one admin command |
| `daoc progress upgrade\|import\|inspect …` | Saved-progress tools |
| `daoc graphics [status\|enable\|disable\|update …]` | Optional graphics patches |
| `daoc dev ship-pins` | Write the effective pins into `manifest.json` |
| `daoc dev e2e [a] [p]` | End-to-end acceptance run on ports 20300/20400 |

See [PLAY.md](PLAY.md), [GRAPHICS.md](GRAPHICS.md), [UPDATING.md](UPDATING.md)
and [DEVELOPMENT.md](DEVELOPMENT.md).

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
