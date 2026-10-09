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
│   └── DAoCLauncher.app/    # Aqua-session wine wrapper (GL baseline mode)
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
    "url": "<gcenx release asset url>",
    "tarball": "wine-staging-11.18-osx64.tar.xz",
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

1. Verify/fetch the Gcenx Wine Staging tarball (SHA-256), extract to `dist/wine/`.
2. Verify/fetch the pinned OfflineDAoC release parts (per-part + archive SHA-256),
   join, extract with zip-slip validation.
3. Apply the client encryption-bypass patch to `game.dll` (byte-verified against
   the recorded pristine hash).
4. Install the launcher wrapper (WINEPREFIX bootstrap, GL baseline mode).

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