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

- Living Server (spec 2), graphics patches, the benchmark gate, and games older than 0.37 in
  the GUI: they stay available through the `daoc` CLI of a git Checkout.
- A native reimplementation of any `daoc_cli` logic.
- Auto-update (Sparkle); the launcher links to a newer release instead.
- Server updates that follow the branch head (`daoc server update`) in the GUI.

## Requirements removed from the player's path

| Today | Source | After |
|---|---|---|
| Xcode CLT (`/usr/bin/python3`, git) | `daoc:27-31` | bundled Python; no git call in the app's paths |
| cmake | `daoc_cli/server.py:182` | prebuilt server |
| .NET 10 SDK, ~10 min compile | `server/tools/setup-dotnet.sh`, `build-release.sh` | prebuilt server |
| git clone (~400 MB) | `daoc_cli/server.py:161` | prebuilt server |
| two terminals, admin TUI | `daoc-server.sh:115` | `start --detach`, launcher window |
| code and data in one folder | `daoc_cli/checkout.py:67-86` | code root + data home |

The .NET 10 *runtime* for the new client (`newclient.ensure_dotnet`) is still installed into
`~/.dotnet` by `server/tools/setup-dotnet.sh`; it needs neither CLT nor cmake.

## 1. Bundle layout and data home

```
OfflineDAoC.app/Contents/
├── MacOS/OfflineDAoC          # SwiftUI shell (arm64)
├── Resources/
│   ├── python/                # python-build-standalone 3.12, arm64, signed
│   └── daoc/                  # the code root
│       ├── daoc               # the same sh launcher as the repo's ./daoc
│       ├── daoc_cli/  manifest.json  version.txt
│       ├── client/DAoCLauncher.app
│       └── server/tools/setup-dotnet.sh
└── Info.plist                 # LSMinimumSystemVersion 26.0
```

`Checkout(root=None, home=None)` splits the root in two:

- **Code root** (read-only in the bundle): `manifest.json`, `version.txt`, `daoc_cli/`,
  `client/DAoCLauncher.app` (`launcher_src`), `server/tools/`, and in a git Checkout
  `server/vendor`, `client/input-helper`, `client/tools` (source builds and the benchmark).
- **Data home** (writable): `dist/`, `server/dist/daoc-server/`, `downloads/`, `upstream/`,
  `.daoc/`, `logs/app/`, and the maintainer's `evidence/` and `.e2e.lock`.

`home` is the argument, else `$DAOC_DATA`, else `root`, so a git Checkout behaves exactly as
today. The name is not `DAOC_HOME`: `daoc-server.sh:35` and `build-release.sh` already read
`DAOC_HOME` as the server folder, and every child inherits daoc's environment.

The app sets `DAOC_DATA=~/Library/Application Support/OfflineDAoC` (or an adopted Checkout).
App updates replace the bundle and never touch the data home.

- **One launcher.** `./daoc` uses `../python/bin/python3` beside its folder when that exists
  (the bundle) and skips the CLT check; otherwise it keeps today's CLT check and
  `/usr/bin/python3`.
- **Install `daoc` command…** (app menu) runs `daoc self-install`. When `home != root` the
  wrapper also exports `DAOC_DATA`, so the Terminal and the GUI share one install. A wrapper
  `daoc` did not write is never replaced (existing rule).
- **Adopt.** When `~/.local/bin/daoc` is a `daoc` wrapper (its marker line) whose `CHECKOUT=`
  folder holds a `manifest.json`, Setup offers "Use my existing install": that folder becomes
  `DAOC_DATA` in place; nothing moves.
- **No git in the bundle.** `/usr/bin/git` without the CLT is a stub that opens the CLT
  install dialog. The overview's newer-release line and `daoc status --json` skip git when the
  code root has no `.git`. `daoc server install --from-source` refuses when the code root has
  no `server/vendor` (the bundle), naming a git Checkout as the way to build.
- `daoc_cli` stays Python 3.9-compatible (CLT) and runs on the bundled 3.12; the 373 existing
  tests pass on both today. python-build-standalone reads `/private/etc/ssl/cert.pem`, so
  `urllib` HTTPS works unchanged (verified with 3.12.13 against api.github.com).

## 2. Event seam in `daoc_cli`

With `DAOC_EVENTS=<fd>` (a decimal file descriptor), `daoc` writes JSON lines to that fd,
besides its unchanged stderr text, and reads answers as JSON lines on stdin. One process per
command, no daemon. The process exit status is authoritative; there is no `done` event.
Commands that `execv` another program (`server start/stop/status`, `admin`, `progress`,
`graphics`) emit nothing after the exec, and the GUI reads their stdout and exit status.

| Event | Emitted by | GUI |
|---|---|---|
| `{"t":"step","msg":…}` | `errors.say` | step label, log |
| `{"t":"download","path":…,"bytes":N\|null,"what":…}` | `release.download` (path = the `.part` file, bytes = Content-Length) and `client._download` (curl; bytes null) | progress bar by polling the file's size; indeterminate when bytes is null |
| `{"t":"ask","id":N,"question":…,"default":false}`; stdin `{"id":N,"answer":bool}` | `errors.ask` | Yes/No sheet |
| `{"t":"secret","id":N,"what":"login"}`; stdin `{"id":N,"account":…,"password":…}` | `keychain.save_interactive` | account form |
| `{"t":"error","msg":…,"code":N}` | `cli.main`'s `DaocError` branch | alert, "Show log" |

Rules:

- `errors.interactive()` = `sys.stdin.isatty() or events.on()`, read at call time. It replaces
  the `isatty()` checks at `server.py:242,299`, `keychain.py:78`, `client_runtime.py:124` and
  `self_install.py:64`. `keychain.unlock` (`keychain.py:44`) keeps `isatty()`: `security
  unlock-keychain` prompts on a terminal itself, and the app runs in the unlocked GUI session.
- Events are additive: stderr text, exit codes and existing tests stay unchanged.
- In event mode every child gets `stdin=/dev/null` unless it is given input, so no child can
  read the answer channel.
- **Secret.** The account goes to `security add-generic-password … -w <account>` as today. The
  password goes to `security add-generic-password … -w` (bare `-w`, as today) on stdin, twice,
  in a new session (`start_new_session=True`): without a controlling terminal `security`
  reads the prompt answers from stdin (verified on macOS 27.0.1). The Keychain write never
  puts the password on argv. Account creation goes through the server's own admin CLI
  (`daoc admin accounts create <name> <password>`), which takes it as an argument, so there
  it is on the server CLI's argv. A password containing a line break is refused.
- `daoc status --json` (hidden group, offline) gives the launcher its state:

  ```json
  {"schema": 1, "version": "0.4.0", "home": "…",
   "game": {"name": "0.37b", "version": "0.37", "edition": "sluaghbinder"},
   "client": "original", "switching_to": null,
   "installed": {"server": true, "original_client": true, "new_client": false},
   "wine": "rosetta",
   "server": {"running": true, "detail": "running (pid 4242)"},
   "client_running": null, "account_saved": true, "save": "sluaghbinder"}
  ```

  `running` and `account_saved` are null when unknown. `account_saved` uses
  `security find-generic-password` without `-w`, so no secret is read while polling.
- Cancel = SIGINT to the child's process group; the existing exit-130 paths run. Downloads
  restart the interrupted file or part; finished, verified files stay cached.

## 3. CI, prebuilt server, signing

### Prebuilt server

A release tag's manifest cannot name the SHA-256 of an asset built from that tag, so the
prebuilt server is published first, keyed by the server pin, and its pin ships in an ordinary
reviewed commit:

1. `server-prebuilt.yml` (manual dispatch, input `version`, macOS arm64 runner) runs
   `daoc dev pack-server <version>`: build the Shipped server pin from source into a scratch
   data home, then pack `server/dist/daoc-server/` as
   `daoc-server-<version>-<ref12>-osx-arm64.tar.xz` with root folder `daoc-server/`,
   symlinks kept, `config/ data/ logs/ run/` left out, `.daoc-pin.json` included.
2. It uploads the tarball to the release `server-<version>-<ref12>` of this repo.
3. It runs `daoc dev ship-prebuilt <version> <tarball> <url>`, which writes
   `versions.<version>.server.prebuilt: {url, bytes, sha256}` into `manifest.json`, and opens
   a pull request with the release App token.

`daoc server install`:

- The effective pin has `prebuilt` and no `--from-source`: download into
  `downloads/server/`, verify size and SHA-256 (a mismatch stops before unpacking), refuse
  while the server runs, extract into a staging folder with path checks (no absolute paths,
  no `..`, symlinks must stay inside), refuse a tarball holding `config/ data/ logs/ run/`,
  require its `.daoc-pin.json` `ref` to equal the pin's, then replace each top-level entry the
  tarball has and nothing else. User folders survive.
- Otherwise build from source as today (`--from-source` forces it).
- `updates.resolve_latest` drops `prebuilt` from the server pin it returns, so a Local pin
  (`daoc server update`) never carries one and builds from source; `daoc dev ship-pins` then
  drops the stale `prebuilt` from the manifest, because `pins._merge` keeps only the pin's keys.
- `build-release.sh` writes to `$DAOC_SERVER_OUT` when set (else `server/dist/daoc-server` as
  today); `server.install` sets it to the data home's server folder.
- The install record (`.daoc-pin.json`) never contains `prebuilt`.

The server stays ad-hoc signed (`build-release.sh:210`). Python's `urllib` and curl set no
quarantine, so Gatekeeper never assesses it; trust rests on the SHA-256 pin, as for Wine
(`DESIGN.md:338`).

### Admin interface

No server repo change. `daoc-admin <command> --json` exists for every command at the
shipped 0.37 `ref`. `bots list --json` prints an array of `{id, name, realm, class, race,
level, zone, activity, goal, online, deleting}` (realm `Albion`/`Midgard`/`Hibernia`).
`bots create --realm alb|mid|hib|all --level 1|50 --count 1-100` turns the population on.
With the server down, `daoc-admin` exits 5 with `error: …` on stderr.

### App build, signing, notarization

`app.yml`, when a `v*` release is published (release-please publishes with the release App
token, not `GITHUB_TOKEN`, so publishing starts workflows; `server-*` prereleases are skipped):

1. `app/build-app.sh`: `swift build -c release`, assemble the bundle (section 1), embed
   python-build-standalone (URL and SHA-256 pinned in `app/python.lock`).
2. `app/sign-app.sh`: `codesign --force --options runtime --timestamp` inside out (every
   Mach-O under `Resources/python`, then the bundle); no entitlements unless the self-test
   needs `com.apple.security.cs.allow-unsigned-executable-memory`.
3. DMG (`hdiutil create`), `xcrun notarytool submit --wait`, `xcrun stapler staple`, upload to
   the tag's release.

Secrets, in the repository's `release` environment (which admits `v*` tags; `main` admits only the branch): `DEVELOPER_ID_P12`, `P12_PASSWORD`, `NOTARY_KEY_ID`, `NOTARY_ISSUER`, `NOTARY_KEY_P8`.

`client/DAoCLauncher.app` ships inside the signed bundle; `daoc client install` copies it into
the data home, where `daoc graphics` may rewrite its `launch` (`DESIGN.md:241`). The copy
carries no quarantine, so this behaves as today.

## 4. Setup wizard and launcher

### Headless server

`daoc-server.sh start --detach`: the existing background start and readiness wait
(`daoc-server.sh:96-114`), then exit 0 without `exec daoc-admin`; a server that is not ready
after the wait fails with the log's last lines; an already running server exits 0.
`daoc server start --detach` passes it through. The server keeps running under `nohup` when
the app quits; on quit the app asks "Stop the server?" (default yes).

### Setup wizard

Shown when the data home has no Server install and no adopted Checkout.

1. **Check**: arm64; macOS ≥ 26; free space (8 GB, +36 GB with the new client); Rosetta
   (`/Library/Apple/usr/libexec/oah/libRosettaRuntime` exists). Without Rosetta: macOS ≥ 27
   picks `--wine arm64`; below 27, "Install Rosetta" runs
   `softwareupdate --install-rosetta --agree-to-license` with administrator privileges
   (macOS's own prompt). Offer "Use my existing install" when a Checkout is found.
2. **Choose**: Game 0.37b (default) or 0.37; "Also install the new client (+34 GB)" unchecked.
3. **Install**, each command on the event stream, in order:
   1. `daoc game switch <game>` without `--client`. On an empty data home it installs the
      server (prebuilt), writes `config/edition` and records the Selection, and installs no
      client (`game.py:139-179`). `daoc server install` alone would skip
      `server.set_edition`, so Setup never calls it directly.
   2. `daoc client install [--wine arm64]`: the original client for the selected game.
   3. If chosen, `daoc client install --client new`, which also makes it the default client.

   One progress bar per download. Stop is offered only while a download runs; otherwise
   quitting asks "Let it finish?".
4. **Account**: name and password; `daoc server start --detach`;
   `daoc admin accounts create <name> <password>`; `daoc client login` with the `secret`
   event answered from the same form.
5. **Done**: open the launcher.

Setup keeps no progress file: on launch, `daoc status --json` says which steps are done
(`installed.server`, `installed.original_client`, `account_saved`), and every command resumes
its own work.

### Launcher

- **Header**: Game, client, Wine; server state from `daoc status --json`, polled every 3 s while
  the window is visible.
- **Play**: `daoc server start --detach` if needed, then `daoc client start`.
  **Stop client**: `daoc client stop`.
- **Server**: Start, Stop, "Open admin console" (Terminal.app runs the wrapper-free command
  `<Resources>/daoc/daoc server start` with `DAOC_DATA`, which attaches the TUI to the running
  server, `daoc-server.sh:64`), "Show logs".
- **Bots** (enabled while the server runs): per realm (Albion, Midgard, Hibernia) the roster
  and online counts from `daoc admin bots list --json`, excluding `deleting` bots; **+ Lv.1**
  and **+ Lv.50** run `daoc admin bots create --realm <alb|mid|hib> --level <1|50> --count <n>`
  with one shared stepper (1–100, default 10); a population switch
  (`daoc admin population on|off`), refreshed after every create. Delete, classes, goals and
  options stay in the admin console.
- **Settings**: switch game (`daoc game switch`, its `ask` sheets), add the new client, Wine
  flavour (`daoc client install --wine …`), change account (`daoc client login`).
- **Updates**: "Check for updates" runs `daoc client update --check`; "Update client" runs
  `daoc client update`; a newer app release (GitHub `releases/latest` of
  trozzelle/OfflineDAoC-macOS against `version.txt`) shows a download link.
- Menu: "Install `daoc` command…".

## 5. Errors and testing

### Errors

- Every failure is a `DaocError` with its existing message and code (0 ok, 1 failure, 2 refusal,
  130 interrupted). The GUI shows the `error` event's message (or the stderr tail for
  `execv`'d commands) with "Show log".
- Each GUI-run command's stderr goes to `<home>/logs/app/<time>-<group>-<action>.log`.
- Recovery is resume, never rollback: rerun the same command.
- At launch the shell runs `<Resources>/daoc/daoc --version`; a failure says to download the
  app again.

### Tests

- `tests.yml`: the existing `/usr/bin/python3` job, plus the same suite on python-build-standalone
  3.12 (the `app/python.lock` build).
- New permanent unit tests:
  - `Checkout(home=…)` / `DAOC_DATA`: installs, state and downloads under home; manifest and
    launcher source under root; without either, today's layout.
  - Events: `ask` round trip (yes, no, EOF → no); `secret` keeps the password off argv;
    `interactive()` gives the same refusals and prompts in both modes; stderr and exit codes
    are unchanged with events on; children get no stdin in event mode.
  - Prebuilt install: SHA-256 mismatch stops before unpacking; a Local pin and `--from-source`
    build from source; `config/ data/ logs/ run/` survive; a tarball whose record names
    another ref, or which holds user folders or escaping paths, is refused.
  - `daoc dev pack-server` / `ship-prebuilt`: the tarball leaves user folders out and keeps
    symlinks; the manifest gains `prebuilt` with the tarball's size and hash.
  - `daoc-server.sh start --detach` against a fake `CoreServer`: exits 0 once ready without the
    TUI; a server that dies fails with the log's last lines; a running server exits 0.
  - `daoc status --json`: shape and nulls, without git in the code root.
  - `./daoc` launcher: prefers `../python/bin/python3` and skips the CLT check.
- Swift (`swift test` in `app/`): event decoding, the Setup command plan, the bots counts.
- CI smoke on the arm64 runner: mount the DMG, `spctl --assess --type execute -v` and
  `codesign --verify --deep --strict`; `OfflineDAoC --self-test` runs `daoc --version` and
  `daoc status --json` through the bundled Python under the hardened runtime.
- Manual pre-release checklist, on a clean macOS user account: download the DMG in Safari, first
  open through Gatekeeper, full Setup with the original client, Play to the world, bot buttons,
  quit with the server running. Not in CI: the 5 GB / 34 GB client downloads and Wine rendering.

## Verified premises

- `daoc game switch` on an empty data home: see Setup step 3 (`game.py:139-179`).
- `daoc-admin` talks to the running server's socket (`daoc-admin:8`, `run/admin.sock`), so
  account creation and the Bots panel need the server running.
- `security add-generic-password -w` reads the password from stdin without a controlling
  terminal.
- python-build-standalone 3.12 runs the existing suite and makes HTTPS requests.

## Resolved premise

- CPython from python-build-standalone 3.12.16 runs under the hardened runtime with no
  entitlements (verified by `--self-test` on an ad-hoc, runtime-signed bundle); the bundle
  is about 59 MB.

## Spec 2 (later): Living Server on macOS

chris4aker's Living Server C# fork as its own branch in OfflineDAoC-macOS-server, selectable as
a game through `daoc game switch`, with its feature switches in a launcher tab.
