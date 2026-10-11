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
│   ├── tools/               #   macOS build scripts (osx-arm64, libDetour.dylib, codesign)
│   └── deploy/              #   server folder templates + daoc-server.sh / daoc-admin
├── client/
│   ├── install-client.sh    # wine + OfflineDAoC release + client patch + launcher
│   ├── apply_game_patch.py  # game.dll encryption-bypass patch (byte-verified)
│   ├── DAoCLauncher.app/    # Aqua-session wine wrapper (mtld3d + x87sidecar)
│   ├── bench-run.sh         # performance gate (5-min scripted play, avg/p95/1%-low)
│   ├── bench-drive.sh       #   scripted NPC interaction + movement for the gate
│   ├── input-helper/        #   SendInput helper run inside the prefix (mingw-w64)
│   └── tools/               # launch-client.sh (Keychain + hang watchdog),
│                            # stop-client.sh, frametime/ (per-present probe dylib)
├── install-server.sh        # pull pinned upstream → overlay → build → dist/
├── update.sh                # bump pins in manifest.json
├── e2e-test.sh              # scripted end-to-end acceptance
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

Prerequisites: .NET 10 SDK, cmake, g++, python3 — all free.

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