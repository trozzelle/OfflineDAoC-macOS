# Design

How this repo is put together, and why.

## Layout

```
daoc-macos/
├── README.md
├── LICENSE                  # GPL-3.0 — server patches inherit the upstream license
├── manifest.json            # pinned upstream versions + hashes (single source of truth)
├── server/                  # macOS server port overlay, vendored from the port work
│   ├── patches/             #   source patches applied to the upstream snapshot
│   ├── vendor/              #   arm64-safe System.Data.SQLite (SQLITE_STANDARD build)
│   ├── tools/               #   macOS build scripts (osx-arm64, libDetour.dylib, codesign),
│   │                        #   ProgressImport/ (daoc-progress source)
│   └── deploy/              #   server folder templates + daoc-server.sh / daoc-admin /
│                            #   daoc-progress
├── client/
│   ├── apply_game_patch.py  # game.dll encryption-bypass patch (byte-verified)
│   ├── fetch_release.py     # OfflineDAoC release fetcher (per-part + archive SHA-256)
│   ├── DAoCLauncher.app/    # Aqua-session wine wrapper (mtld3d + x87sidecar)
│   ├── bench-run.sh         # performance gate (5-min scripted play, avg/p95/1%-low)
│   ├── bench-drive.sh       #   scripted NPC interaction + movement for the gate
│   ├── input-helper/        #   SendInput helper run inside the prefix (mingw-w64)
│   └── tools/               # launch-client.sh (Keychain + hang watchdog),
│                            # stop-client.sh, kill-client.sh (install-scoped
│                            # teardown), frametime/ (per-present probe dylib)
├── install-server.sh        # pull pinned upstream → overlay → build → dist/
├── install-client.sh        # wine + OfflineDAoC release + client patch + launcher
├── update.sh                # bump pins in manifest.json
├── e2e-test.sh              # scripted end-to-end acceptance
├── .github/CODEOWNERS       # @trozzelle owns the repository
└── docs/
```

`downloads/` (release caches), `upstream/` (clones), `dist/`, and wine prefixes are
gitignored — fetched at install time, never committed.

## Manifest

`manifest.json` pins what the installers pull:

```json
{
  "schema": 1,
  "server": {
    "upstream": "https://github.com/catastrophic-impact/daoc-offline-linux-server-bots",
    "ref": "<commit sha>"
  },
  "client": {
    "release_url": "https://github.com/shadowofze/OfflineDAoC/releases/download/v0.35b/",
    "version": "0.35b",
    "manifest_asset": "download-manifest.json"
  },
  "wine": {
    "url": "<athei/wine-build release asset url>",
    "tarball": "wine-cx-26.3.0-8-macos-x86_64.tar.xz",
    "sha256": "<recorded>"
  }
}
```

Server pin = immutable git commit. Client pin = release tag; per-part and
whole-archive SHA-256 come from the release's own `download-manifest.json` and are
verified at install time (same scheme as upstream's `Get-OfflineDAoC.ps1`). Wine pin
= tarball SHA-256 recorded here.

## Server install

The macOS server port is a source-patch port, not a fork:

1. Clone the pinned upstream commit into `upstream/server/`.
2. Overlay `server/` (patch `patches/010-adminsockethost-macos-close.patch` via
   `git apply`, vendor `System.Data.SQLite`, add macOS `tools/` + `deploy/`).
3. Run the port's `tools/build-release.sh` → `dist/daoc-server/` (self-contained
   osx-arm64 .NET publish, cmake-built `libDetour.dylib`, ad-hoc codesigning).
   It snapshots the source from `DAOC_SOURCE_REPO`; `install-server.sh` pins that
   to the verified `upstream/server/` clone, which is also the default when the
   build script or `fetch-upstream-db.sh` runs on its own.

Prerequisites: .NET 10 SDK, cmake, g++, python3 — all free.

## Server updates and saved progress

`dist/daoc-server/` is both the build output and the user's install, so a rebuild
must never touch user state:

- `build-release.sh` refuses while the server runs, then deletes only what the build
  owns (`bin/`, `defaults/` and the top-level files in its `EXTRAS` array).
  `config/`, `data/`, `logs/` and `run/` survive; `navmesh/` is refreshed in place.
- The release zip leaves those folders out and stores `bin/config`, `bin/logs` and
  `bin/navmesh` as symlinks (`zip -y`). Following them would pack the builder's
  config and logs, plus a second copy of the navmeshes.

A save keeps the world it was created from, so new world data in
`defaults/world.sqlite` needs an explicit migration. `daoc-progress` is upstream
Offline DAoC's Windows-only IMPORT PROGRESS engine, ported (`server/tools/ProgressImport`).
It is published into `bin/` and links the vendored System.Data.SQLite:

- **upgrade**: the result starts as `defaults/world.sqlite`. It receives this
  server's progress tables and keeps the install's settings (edition, population,
  options, XP rates).
- **import**: the result starts as this server's own save. Its progress tables are
  replaced from another save, which is copied first so the source is never written.
- `progress-policy.json` lists the progress tables (copied, then verified by row count
  and content) and the tables to clear. Every old item template the world lacks is
  kept, because `Inventory`, `househookpointitem` and `CharacterXOneTimeDrop` all
  reference templates. An owned house whose lot the world lacks aborts the run.
- The result is built in `data/progress-backups/<time>/` next to a backup of the
  current save, integrity-checked, and swapped in only after stale
  `-wal`/`-shm`/`-journal` files are removed. It is rolled back if the check after the
  swap fails. Both commands refuse while this server, or the source save's server,
  is running.

## Client install

1. Verify/fetch athei's wine-build tarball (SHA-256), extract to `dist/wine/`
   (flat `bin/`, `lib/`). It is CrossOver 26.3 Wine with i386 support, the
   x87sidecar Rosetta x87 JIT and mtld3d; its `compatdb.so` attaches x87sidecar
   to every i386 process and picks mtld3d as D3D9.
2. Verify/fetch the pinned OfflineDAoC release parts (per-part + archive SHA-256),
   join, extract with zip-slip validation.
3. Apply the client encryption-bypass patch to `game.dll` (byte-verified against
   the recorded pristine hash).
4. Initialize/update the prefix (win10), replace the profile-folder symlinks with
   real directories (no TCC prompt for ~/Documents), install the launcher wrapper.

Why this wine: the 1.127 client's game thread spends ~70% of its time in Rosetta's
x87 emulation (libRosettaRuntime) under stock Wine, which caps it at ~7 FPS.
x87sidecar removes that cost; mtld3d replaces wined3d's GL path with Metal.
The launcher's `DAOC_FPS_OVERLAY=1` shows the Metal Performance HUD. The evidence
behind this, and the other client pitfalls (TCC prompt, the `crossover` prefix
user, the linkdead wait after a kill), is in `docs/CLIENT-NOTES.md`.

The release ships the original 1.127 Windows client; the patch lets it talk to a
local OpenDAoC server without breaking on the encryption handshake.

## Benchmark gate

`client/bench-run.sh` measures the client the player gets, not a synthetic scene:

- **Login** — `client/tools/launch-client.sh` with the game account from the login
  Keychain and the character from the server database (`DAOC_CHARACTER`, else the
  most recently played). The game port is the `<Port>` in the server's
  `config/serverconfig.xml`.
- **Play** — `bench-drive.sh` drives the character through `sendinput.exe`, a
  mingw-built helper that runs inside the game's own prefix and wineserver, so no
  macOS Accessibility permission is needed. Each cycle `/jump`s to a townsfolk NPC,
  right-clicks it (interact), closes the window and walks a movement pattern.
  `/jump` and `/target` need GM rights: the bench raises a player account to gm
  for the run, records that in `run/bench-gm-raised`, and restores player on exit
  or signal (or at the start of the next run, if the server was gone).
- **Probe** — `client/tools/frametime/ftlog.dylib` (universal: x86_64 wine and
  arm64 x87sidecar both load it) swizzles `-[CAMetalLayer nextDrawable]` and logs
  one timestamp per presented frame. The launcher injects it with
  `DYLD_INSERT_LIBRARIES` when `DAOC_FTLOG_DIR` is set; it cannot be set by the
  caller because SIP strips `DYLD_*` when the `/bin/bash` launcher starts.
- **Verdict** — over exactly the play window: PASS at average ≥ 60 FPS and p95
  ≤ 16.7 ms (17.0 ms when mtld3d reports vsync on); 1%-low FPS is diagnostic.
  The run is invalid (exit 2) if the probe wrote nothing, the renderer's vsync state
  is missing from the mtld3d log, the server stopped during play, or the character
  ended under 300 units from the last NPC it interacted with (read from the server
  database after logout).

## E2E acceptance

`e2e-test.sh` on a clean checkout: install server → boot it (alternate ports when
the primary are busy) → create an account via `daoc-admin` → install client →
launch → pass when the server log shows the login reaching character select and the
client process is still alive ≥60 s later → exit 0. Manual UAT (renders, plays)
gates final acceptance after that.

## Server-side notes

Upstream game-logic issues (e.g. character creation with race 21 — HiberniaMinotaur
— throws `KeyNotFoundException` in the server's stat validator) are documented in
`docs/SERVER-NOTES.md`, never patched here.