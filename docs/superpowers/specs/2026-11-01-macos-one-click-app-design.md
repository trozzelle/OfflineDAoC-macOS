# OfflineDAoC.app: one-click install and launcher for macOS

Status: approved design (spec 1 of 2). Spec 2, Living Server on macOS, follows this one.

## Goal

A signed, notarized `OfflineDAoC.app` in a DMG takes an Apple Silicon Mac from nothing to
playing Offline DAoC with no Terminal, no Xcode Command Line Tools, no Homebrew and no local
server build. Its first run is a Setup wizard; afterwards it is the launcher (Play, server,
bots, settings, updates). It is the macOS counterpart of chris4aker's Living Server Setup
(`tools/installer` in OfflineDAoC-LivingServer), and follows the same rule: the GUI runs the
existing tested engine (`daoc_cli`) and only adds progress and plain choices over it.

## Non-goals

- Living Server (spec 2), graphics patches, and games older than 0.37 in the GUI: they stay
  available through the `daoc` CLI.
- A native reimplementation of any `daoc_cli` logic.
- Auto-update (Sparkle); the launcher links to a newer release instead.
- Server updates that follow the branch head (`daoc server update`) in the GUI.

## Requirements removed from the player's path

| Today | Source | After |
|---|---|---|
| Xcode CLT (`/usr/bin/python3`, git) | `daoc:27-31` | bundled Python; git only for CLI-only paths |
| cmake | `daoc_cli/server.py:182` | prebuilt server |
| .NET 10 SDK, ~10 min compile | `server/tools/setup-dotnet.sh`, `build-release.sh` | prebuilt server |
| git clone (~400 MB) | `daoc_cli/server.py:161` | prebuilt server |
| two terminals, admin TUI | `daoc-server.sh:115` | `start --detach`, launcher window |
| code and data in one folder | `daoc_cli/checkout.py:67-86` | code root + data home |

The .NET 10 *runtime* for the new client (`newclient.ensure_dotnet`) is still installed into
`~/.dotnet` by `setup-dotnet.sh`; it needs neither CLT nor cmake.

## 1. Bundle layout and data home

```
OfflineDAoC.app/Contents/
├── MacOS/OfflineDAoC          # SwiftUI shell (arm64)
├── Resources/
│   ├── python/                # python-build-standalone 3.12, arm64, signed
│   ├── daoc/                  # daoc_cli/, manifest.json, version.txt, client/, server/deploy, server/tools
│   └── daoc                   # sh entry: runs Resources/python on daoc_cli (no CLT check)
└── Info.plist                 # LSMinimumSystemVersion 26.0
```

`Checkout(root, home=None)` splits the root in two:

- **Code root** (read-only, in the bundle): `manifest.json`, `version.txt`, `daoc_cli/`,
  `client/DAoCLauncher.app` (`launcher_src`), `server/tools`, `server/deploy`.
- **Data home** (writable): `dist/`, `server/dist/daoc-server/`, `downloads/`, `upstream/`,
  `.daoc/`, and the new `logs/app/`.

`home` defaults to `root`, so a git Checkout behaves exactly as today. The app sets
`DAOC_HOME=~/Library/Application Support/OfflineDAoC`. Every `Checkout` path except the code
root's moves to `home`. App updates replace the bundle and never touch the data home.

- The app's "Install `daoc` command…" menu item writes the existing `~/.local/bin/daoc`
  wrapper (`self_install`) pointing at the bundled Python and `DAOC_HOME`, so the Terminal and
  the GUI share one install. A wrapper `daoc` did not write is never replaced (existing rule).
- When `~/.local/bin/daoc` is a `daoc` wrapper naming a Checkout, Setup offers "Use my existing
  install": that Checkout becomes `DAOC_HOME` in place (nothing moved).
- `daoc_cli` stays Python 3.9-compatible (CLT) and must also run on the bundled 3.12.
- `daoc graphics` and `--from-source` builds still need git and the build toolchain; they keep
  their existing errors and fixes when those are missing.

## 2. Event seam in `daoc_cli`

With `DAOC_EVENTS=1`, `daoc` writes JSON lines to fd 3, besides its unchanged stderr text, and
reads answers as JSON lines on stdin. One process per command (no daemon).

| Event | Emitted by | GUI |
|---|---|---|
| `{"t":"step","msg":…}` | `errors.say` | step label, log |
| `{"t":"download","path":…,"bytes":N,"what":…}` | `client._download`, `newclient._fetch_verified`, the prebuilt server fetch | progress bar by polling the file's size against `bytes` |
| `{"t":"ask","id":…,"question":…,"default":false}`; stdin `{"id":…,"answer":bool}` | `errors.ask` | Yes/No sheet |
| `{"t":"secret","id":"login",…}`; stdin `{"account":…,"password":…}` | `keychain.save_interactive` | account form; `daoc` writes the Keychain |
| `{"t":"error","msg":…,"code":N}` | top-level `DaocError` handler | alert, "Show log" |
| `{"t":"done","code":N}` | exit | next step |

Rules:

- `interactive()` = `sys.stdin.isatty() or events_on()` replaces the `isatty()` checks at
  `server.py:242,299`, `keychain.py:44,78`, `client_runtime.py:124` and `self_install.py:64`,
  so refusals and prompts are one logic in both modes.
- Events are additive: stderr text, exit codes and existing tests stay unchanged.
- `daoc status --json` (the overview) gives the launcher its read-only state: installs,
  Selection, Wine flavour, server running, account saved, updates available.
- Passwords are never stored by the GUI; it relays them once to `daoc`'s Keychain entry.
- Cancel = SIGINT to the child; the existing exit-130 paths run and downloads resume from cache.

## 3. CI, prebuilt server, signing

### Prebuilt server

`release-assets.yml`, on release-please's tag, on a macOS arm64 runner, per game Version in
`manifest.json`:

1. `daoc server install` (from source, the pinned `ref` and `navmesh_ref`).
2. Pack `server/dist/daoc-server/` like the release zip: `bin/`, `defaults/`, `navmesh/` and
   the top-level files, without `config/ data/ logs/ run/`, symlinks kept, as
   `daoc-server-<version>-<ref12>-osx-arm64.tar.xz`.
3. Upload to this repo's release.

`daoc dev ship-pins` writes `server.prebuilt: {url, bytes, sha256}` per Version into
`manifest.json` in a reviewed commit.

`daoc server install`:

- Effective pin is the Shipped pin and has `prebuilt`, and no `--from-source`: download, verify
  the SHA-256 (mismatch stops before unpacking), refuse while the server runs, delete only what
  the build owns (`bin/ defaults/` and the `EXTRAS` files, as `build-release.sh:109`), unpack,
  write `.daoc-pin.json`.
- Otherwise (Local pin, `--from-source`, no `prebuilt`): build from source as today.

The server stays ad-hoc signed (`build-release.sh:210`). curl sets no quarantine, so Gatekeeper
never assesses it; trust rests on the SHA-256 pin, as for Wine (`DESIGN.md:338`).

### Server repo change

OfflineDAoC-macOS-server: `daoc-admin bots list --json` prints one array of
`{name, realm, level, class, online}`. The shipped server `ref` for 0.37 moves to a commit that
has it.

### App build, signing, notarization

`app.yml`, on the same tag:

1. `xcodebuild` the SwiftUI shell.
2. Embed python-build-standalone (URL + SHA-256 pinned in the workflow) and the code root.
3. `codesign --options runtime --timestamp` inside out: each Mach-O in `Resources/python`, then
   the bundle. No entitlements by default; add `com.apple.security.cs.allow-unsigned-executable-memory`
   only if the `--self-test` smoke fails without it.
4. DMG, `notarytool submit --wait`, `stapler staple`, upload to the release.

Secrets: `DEVELOPER_ID_P12`, `P12_PASSWORD`, `NOTARY_KEY_ID`, `NOTARY_ISSUER`, `NOTARY_KEY_P8`.

`client/DAoCLauncher.app` ships inside the signed bundle; `daoc client install` copies it into
the data home, where `daoc graphics` may rewrite its `launch` (`DESIGN.md:241`). The copy carries
no quarantine, so this behaves as today.

## 4. Setup wizard and launcher

### Headless server

`daoc-server.sh start --detach`: the existing background start and readiness wait
(`daoc-server.sh:96-114`), then exit 0 without `exec daoc-admin`. On a server that is already
running, it exits 0. `daoc server start --detach` passes it through. The server keeps running
under `nohup` when the app quits; on quit the app asks "Stop the server?" (default yes).

### Setup wizard

Shown when the data home has no installs (and no adopted Checkout).

1. **Check**: arm64; macOS ≥ 26; free space (≈ 8 GB, +36 GB with the new client); Rosetta. No
   Rosetta on macOS ≥ 27 picks `--wine arm64`; below 27 offers "Install Rosetta"
   (`softwareupdate --install-rosetta --agree-to-license`, macOS's admin prompt). Offer
   "Use my existing install" when a Checkout is found.
2. **Choose**: Game 0.37b (default) or 0.37; "Also install the new client (+34 GB)" unchecked.
3. **Install**, each command on the event stream, in order:
   1. `daoc game switch <game>` with no `--client`. On an empty data home it installs the
      server (prebuilt), writes `config/edition` and records the Selection; it installs no
      client, since none is installed or asked for (`game.py:139-179`). `daoc server install`
      alone would skip `server.set_edition`, so Setup never calls it directly.
   2. `daoc client install [--wine arm64]`: the original client for the selected game.
   3. If chosen, `daoc client install --client new`, which also makes it the default client.

   One progress bar per download. Stop is offered only while a download runs; otherwise
   quitting asks "Let it finish?".
4. **Account**: name and password; `daoc server start --detach`; `daoc admin accounts create
   <name> <password>`; save to the Keychain through the `secret` event.
5. **Done**: open the launcher.

`.daoc/setup.json` records the last finished step only to reopen the right page; every command
already resumes its own work.

### Launcher

- **Header**: Game, client, Wine; server state from `daoc status --json`, polled every 3 s while
  the window is visible.
- **Play**: `daoc server start --detach` if needed, then `daoc client start [--client …]`;
  **Stop client**.
- **Server**: Start, Stop, "Open admin console" (Terminal.app runs `daoc server start`, which
  attaches the TUI to the running server, `daoc-server.sh:64`), "Show logs".
- **Bots** (enabled while the server runs): per realm (Albion, Midgard, Hibernia) the roster and
  online counts from `daoc admin bots list --json`, and **+ Lv.1** / **+ Lv.50** buttons running
  `daoc admin bots create --realm <r> --level <1|50> --count <n>` with one shared count stepper
  (default 10); a population switch (`daoc admin population on|off`). Delete, classes, goals and
  options stay in the admin console.
- **Settings**: switch game (`daoc game switch`, its confirmations as `ask` sheets), add or
  remove the new client, Wine flavour, change account (`secret`).
- **Updates**: `daoc client update`; a link to a newer app release.
- Menu: "Install `daoc` command…".

## 5. Errors and testing

### Errors

- Every failure is a `DaocError` with its existing message and code (0 ok, 1 failure, 2 refusal,
  130 interrupted). Code 2 becomes a choice where the CLI already asks; otherwise an alert with
  "Show log".
- Each GUI-run command's stderr goes to `<home>/logs/app/<time>-<command>.log`.
- Recovery is resume, never rollback: rerun the same command.
- At launch the shell runs `Resources/python/bin/python3 -V`; a failure says to download the
  app again.

### Tests

- `tests.yml`: the existing `/usr/bin/python3` job, plus a job on the bundled Python 3.12.
- New permanent unit tests:
  - `Checkout(home=…)`: installs, state and downloads under `home`; manifest and launcher source
    under `root`; without `home`, today's layout.
  - Events: `ask` round trip (yes, no, EOF → no); `secret` reaches a Keychain stub;
    `interactive()` gives the same refusals and prompts in both modes; stderr and exit codes
    are unchanged with events on.
  - Prebuilt install: SHA-256 mismatch stops before unpacking; a Local pin and `--from-source`
    build from source; `config/ data/ logs/ run/` survive; `.daoc-pin.json` is written.
  - `daoc-server.sh start --detach`: exits 0 once ready without the TUI; a server that dies
    fails with the log's last lines.
- Swift: XCTest for event decoding and the wizard's step order only.
- CI smoke on the arm64 runner: unpack the prebuilt server, `start --detach`,
  `daoc admin bots create --count 1`, `bots list --json`, stop; mount the DMG,
  `spctl --assess --type execute` and `codesign --verify --deep --strict`; the app's
  `--self-test` runs `daoc --version` and `daoc status --json` on the bundled Python under the
  hardened runtime.
- Manual pre-release checklist, on a clean macOS user account: download the DMG in Safari, first
  open through Gatekeeper, full Setup with the original client, Play to the world, bot buttons,
  quit with the server running. Not in CI: the 5 GB / 34 GB client downloads and Wine rendering.

## Verified premises

- `daoc game switch` on an empty data home: see Setup step 3 (`game.py:139-179`).
- `daoc-admin` commands go through the running server's admin socket (`daoc-admin:8`,
  `run/admin.sock`), so account creation and the Bots panel need the server running.

## Open premise (resolve first in the plan)

- CPython from python-build-standalone runs under the hardened runtime without entitlements
  (`--self-test` in CI decides; fallback in section 3).

## Spec 2 (later): Living Server on macOS

chris4aker's Living Server C# fork as its own branch in OfflineDAoC-macOS-server, selectable as
a game through `daoc game switch`, with its feature switches in a launcher tab.
