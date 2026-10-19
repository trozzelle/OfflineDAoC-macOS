# Design

How this repo is put together, and why.

## Layout

```
daoc-macos/
├── README.md
├── LICENSE                  # GPL-3.0 — server patches inherit the upstream license
├── daoc                     # sh launcher: CLT check, then daoc_cli on /usr/bin/python3
├── daoc_cli/                # the `daoc` command (Python 3.9 stdlib only)
├── manifest.json            # Shipped pins: upstream versions + hashes
├── version.txt              # this release of daoc (written by release-please)
├── server/                  # macOS build around the server repo (OfflineDAoC-macOS-server)
│   ├── vendor/              #   arm64-safe System.Data.SQLite (SQLITE_STANDARD build)
│   ├── tools/               #   macOS build scripts (osx-arm64, libDetour.dylib, codesign),
│   │                        #   ProgressImport/ (daoc-progress source)
│   └── deploy/              #   server folder templates + daoc-server.sh / daoc-admin /
│                            #   daoc-progress
├── client/
│   ├── DAoCLauncher.app/    # Aqua-session wine wrapper (rosetta: mtld3d + x87sidecar; arm64: FEX + mtld3d)
│   ├── input-helper/        # SendInput helper run inside the prefix (mingw-w64)
│   └── tools/frametime/     # per-present probe dylib for the benchmark gate
├── tests/                   # unit tests for daoc_cli
├── .github/CODEOWNERS       # @trozzelle owns the repository
└── docs/
```

`downloads/` (release caches), `upstream/` (clones), `dist/`, `server/dist/`, wine
prefixes and `.daoc/` (Local pins, update scratch) are gitignored — fetched or
written at install time, never committed.

## The `daoc` command

`daoc` is one command with groups: `server`, `client`, `game`, `admin`, `progress`,
`graphics`, `self-install`, and a `dev` group for maintainers that help leaves out.

- **Launcher.** `./daoc` is a small POSIX sh file. It resolves the Checkout's real
  directory (following symlinks), refuses with `xcode-select --install` as the fix
  when the Xcode Command Line Tools are missing (otherwise macOS would pop the CLT
  install dialog), then runs the `daoc_cli` package on the CLT's `/usr/bin/python3`
  (3.9). `daoc_cli` uses only the standard library, so there is nothing to
  `pip install`. Python runs isolated (`-I`) and loads `daoc_cli` from the Checkout
  by path through `runpy`: `python3 -m daoc_cli` would put the caller's directory
  first on the import path, so a `daoc_cli/` there (another checkout, say) would
  shadow this one. `-I` also keeps `PYTHONPATH` and user site-packages out, while
  child processes still see the caller's environment untouched.
- **The Checkout is the home.** The git checkout holding `daoc_cli` also holds the
  manifest, the Server install (`server/dist/daoc-server/`), the Client install
  (`dist/`), the clones and the download caches. There is no separate home
  directory and no option to pick one.
- **Releases are tags.** Users clone and check out a release tag (`vX.Y.Z`), not
  `main`. `daoc --version` prints `version.txt`; the overview's `Checkout:` line
  names the newest local `v*` tag when HEAD does not contain it, so a checkout on
  `main` past the last release shows nothing.
- **`daoc self-install`** writes `~/.local/bin/daoc`, a short sh wrapper with the
  Checkout path baked in. It is a file, not a symlink, so that when the Checkout
  moves or is deleted the wrapper says so, names the fix (run `./daoc self-install`
  from the new place) and exits 127 instead of failing obscurely. A file at that
  path that `daoc` did not write is never replaced. If `~/.local/bin` is not on
  `PATH`, a terminal user is offered the line for `~/.zprofile` (default no).
- **Passthrough.** `daoc admin`, `daoc progress` and `daoc graphics` hand every
  argument, `--` and options included, to the Server install's `daoc-admin` /
  `daoc-progress` and the pinned `daoc-gfx`.

### What stays shell, and why

- The Server install's own tools (`daoc-server.sh`, `daoc-admin`, `daoc-progress`)
  ship inside the portable server folder and must work there without this
  Checkout; `daoc server start/stop/status` and the passthroughs just run them.
- The Launcher (`DAoCLauncher.app`) is started by LaunchServices (`open -n`) so
  wine runs in the Aqua session; it stays a bundle with a shell entry point.
- The server build pipeline (`server/tools/build-release.sh` and friends)
  mirrors the upstream Linux port's scripts, so the port stays easy to diff and
  re-derive against upstream.

### Conventions

- Data goes to stdout; status, progress and errors go to stderr (`daoc: <msg>`).
- Exit codes: 0 ok, 1 failure, 2 usage error or refusal, 130 interrupted (Ctrl-C).
  `daoc client bench` uses 0 pass, 1 fail, 2 invalid run. The `~/.local/bin/daoc`
  wrapper exits 127 when its Checkout is gone.
- Environment overrides: `DAOC_WINE_HOME`, `DAOC_WINEPREFIX` (wine and prefix),
  `DAOC_CHARACTER`, `DAOC_PORT`, `DAOC_FPS_OVERLAY`, `DAOC_WINEDEBUG`,
  `DAOC_DLL_OVERRIDES`, and for the benchmark gate `DAOC_BENCH_ACCOUNT`,
  `DAOC_BENCH_NPCS`, `DAOC_BENCH_OUT`. `FEX_*`, `MTLD3D_*`, `MTL_*` and `X87_*`
  variables pass through to the client; for the arm64 Wine they override
  `client_runtime.ARM64_ENV` (e.g. `FEX_X87REDUCEDPRECISION=0` for full x87
  precision).

## Manifest

`manifest.json` (schema 2) holds the Shipped pins, per game Version, and the
default Game:

```json
{
  "schema": 2,
  "default": { "game": "0.35b", "client": "original" },
  "versions": {
    "0.35": {
      "server": { "upstream": "<server repo>", "branch": "macos-0.35", "ref": "<commit sha>", "navmesh_ref": "<commit sha>" },
      "original_client": {
        "release_url": ".../releases/download/v0.35b/", "version": "0.35b",
        "root_folder": "OfflineDAoC-v0.35b", "archive_sha256": "…", "parts": [ … ],
        "editions": {
          "sluaghbinder": { "game_dll_sha256": "e1d471bb…" },
          "classic": { "game_dll_sha256": "f55ed6b0…", "game_dll_member": "OfflineDAoC-v0.35b/editions/0.35-no-custom-class/…/game.dll" }
        }
      },
      "new_client": null
    },
    "0.36": {
      "server": { "upstream": "<server repo>", "branch": "macos-0.36", "ref": "<commit sha>" },
      "original_client": { "version": "0.36b", "…": "…" },
      "new_client": {
        "release_url": ".../releases/download/v0.36c/", "version": "0.36c",
        "unpacked_bytes": 33758711327, "parts": [ "19 × {name, bytes, sha256}" ],
        "godot": { "url": "<godot-builds mono macOS zip>", "bytes": 200756622, "sha256": "…" }
      }
    },
    "0.37": {
      "server": { "upstream": "<server repo>", "ref": "<commit sha>" },
      "original_client": { "version": "0.36b", "…": "…" },
      "new_client": {
        "release_url": ".../releases/download/v0.37c/", "version": "0.37c",
        "root_folder": "OfflineDAoC-v0.37c-client-patch", "parts": [ "2 × {name, bytes, sha256}" ],
        "base": { "release_url": ".../releases/download/v0.36c/", "version": "0.36c", "…": "…" },
        "godot": { "…": "…" }
      }
    }
  },
  "wine": { "url": "…", "tarball": "…", "sha256": "…", "min_macos": "26" },
  "wine_arm64": { "url": "…", "image": "…", "sha256": "…", "runtime": "…", "min_macos": "27" },
  "graphics": { "repo": "https://github.com/trozzelle/OfflineDAoC-macOS-graphics", "ref": "<commit sha>" }
}
```

Server pin = immutable git commit of the server repo
([OfflineDAoC-macOS-server](https://github.com/trozzelle/OfflineDAoC-macOS-server)),
with the macOS changes in it as commits; `branch` (default `main`) is the branch
`daoc server update` follows for that Version, and `navmesh_ref` the commit whose
`world/navmesh/` the build uses, when the Version's own commit has none. Client pins
= release tags; per-part (and, for the original client, whole-archive) SHA-256 come
from the release's own `download-manifest.json` and are verified at install time
(same scheme as upstream's `Get-OfflineDAoC.ps1`). Both Editions of a Version share
the b release's archive; `editions` names each one's pristine `game.dll`. From 0.37
upstream ships a Version as an update to the 0.36 base (`"Mode": "patch"`): the
original client pins the base release when the update leaves it unchanged (0.37),
and a new client pin names its full release as `base` and the update's parts as its
own. The Godot pin and the Wine pins = archive SHA-256 recorded here. Graphics pin =
immutable git commit, pulled only by `daoc graphics`.

### Shipped pins and Local pins

A user update never edits `manifest.json`. `daoc server|client|graphics update`
records a Local pin in `.daoc/pins.json` (gitignored), one entry per pin and game
Version (`server@0.36`, `original_client@0.36`, `new_client@0.36`, `graphics`),
along with the Shipped pin it replaced. The Checkout stays clean, so checking out
the next release never conflicts on the manifest. When a release changes that
Shipped pin, the Local pin lapses: it is dropped with a one-line notice and the new
Shipped pin applies. An entry from before game versions is dropped with a notice.
The Server, Original client and New client installs record the pin they were
built from (`.daoc-pin.json` in the install folder), and every "already up to date"
decision reads that record, never the pin. An Original client install made before
the record came from the old tooling, which only installed OfflineDAoC 0.35b: it is
identified by that release's pristine `game.dll` hash, and the record is written
then.
`daoc <group> update --check` only reports what is available.
`daoc dev ship-pins` is the maintainer step: it writes the effective pins into
`manifest.json` for a commit.

## Games and switching

The Selection (`.daoc/selection.json`: Game, Default client, a pending switch) says
what the setup should be; without it, it is inferred from the installs, else the
manifest's `default` applies. Each install records what it is. `daoc` compares the
two and names the `daoc game switch` that fixes a mismatch.

`daoc game switch` (`daoc_cli/game.py`) runs, each step checking what is already done
so a rerun resumes: refuse early (unknown Game, the new client before 0.36 or off
port 10300, an older Version without `--restore`/`--fresh-save`, Sluaghbinder
characters or bots that a Classic classes Game cannot hold) → record the pending
switch → download (the original client's release; the new client staged beside
its install) → stop the client, then the server (asking) → rebuild the server when
the Version's pin differs, write `config/edition` → move the save
(`daoc-progress upgrade --edition=`, or restore/set aside; `data/daoc-game` records
which Game the save was moved into) → bring each installed client along → record
the Selection.

## Update flows

- **Server** (`daoc server update`): resolve the head of the Version's server branch
  (`server.branch`, default `main`) and read which game Version it is synced to
  (`OfflineDaocVersion` in its admin host); another Version than the selected one
  stops the update (a new Version needs a daoc release). A running server is
  stopped only after asking (off a terminal it refuses). Then the server is rebuilt
  from the new commit, and only a successful build records
  it as the Local pin, so a rerun after a failed build retries it. If the new build ships
  different world data, it explains the Progress upgrade and asks before running
  one (default no); otherwise it prints `daoc progress upgrade` for later.
- **Client** (`daoc client update`): re-read the selected Version's release (upstream
  can replace a tag's files), download and verify it, and hash its `game.dll` inside
  the archive. A `game.dll` the Client patch
  does not know is not a Proven build, so it stops with "not a Proven build; it
  needs a shipped update" before changing anything. It refuses while the client
  runs. Graphics patches are carried across through the Graphics project's machine
  interface only: save `daoc-gfx status --json` (in `.daoc/carry-over.json`),
  `textures export` the texture pack, disable every patch, extract the release
  beside `dist/OfflineDAoC`, apply the Client patch to it and record the Local pin,
  then swap it in (the Wine prefix is kept): an interruption leaves either the old
  client or the finished new one. Then re-enable the same patches, `textures
  install --from-dir` the export, and compare `status --json` with the saved one.
  An interrupted update resumes at the re-enable step. Without an
  `upstream/graphics/` clone (`daoc graphics` never ran) there is nothing to carry
  over, so the graphics project is not cloned.
- **Graphics** (`daoc graphics update`): the new commit must pass the contract
  check — its own tests, plus the `daoc-gfx` options, launcher line and machine
  interface this Checkout relies on — before the pin moves.

## Graphics patches (optional)

The graphical patches live in their own repository,
[OfflineDAoC-macOS-graphics](https://github.com/trozzelle/OfflineDAoC-macOS-graphics),
so they can change without touching the install flow, and nothing about them runs
unless asked for. `daoc graphics` clones the pinned commit into `upstream/graphics/`
on first use, refuses to run unless `HEAD` is the pin and `git status` shows no
local changes (the checkout's `d3d9.dll` is what the game loads), and runs that
checkout's `daoc-gfx`
with this install's client app folder and the selected Wine and prefix (`dist/wine`
and `dist/prefix`, or the arm64 pair; `DAOC_WINE_HOME` / `DAOC_WINEPREFIX` override
them, as for the launcher).
With no arguments it opens `daoc-gfx select`, a checklist of the catalog's
patches (`retina`, `srgb`, `textures`, `anisotropy`) that changes only the
patches the user toggles; `enable` / `disable <patch>` do the same
non-interactively.
`daoc-gfx` keeps its records in `.daoc-gfx/` inside the client app folder and
refuses to change anything while that client is running. It writes outside
`dist/OfflineDAoC` in one place: `anisotropy` rewrites the `WINEDLLOVERRIDES`
line of `dist/DAoCLauncher.app/Contents/MacOS/launch` (`d3d9,dxgi=b` →
`d3d9=n,b;dxgi=b`). It recognises that line only if it matches its `STOCK_LINE`
character for character, so editing the line in `client/DAoCLauncher.app`
breaks `enable anisotropy`, and re-running `daoc client install` copies the stock
launcher back (anisotropy then reads `partly on`). `daoc graphics update` runs the
new commit's tests, then checks that its `daoc-gfx --help` still lists `--app`,
`--wine`, `--prefix` and `select`, that its `STOCK_LINE` still appears
exactly once in `client/DAoCLauncher.app`'s launcher, and that the machine
interface the client update uses is there, before moving the pin.

## Server install

The server's source, macOS fixes included, is the server repo
([OfflineDAoC-macOS-server](https://github.com/trozzelle/OfflineDAoC-macOS-server)):
Offline DAoC's server code synced per release, its world data and navmeshes, the
admin host and TUI, and the WorldBuilder. It started as a fork of catastrophic-impact's
Linux repo; this repo keeps only the macOS build around it:

1. Clone the selected Version's pinned commit into `upstream/server/` (pointing an
   older clone's `origin` at the pin's repo first) and verify it. Export the
   navmeshes (`world/navmesh/*.xz` and their manifest) from `navmesh_ref` (or the
   commit itself) for the build.
2. Overlay `server/` (vendor `System.Data.SQLite`, add macOS `tools/` + `deploy/`).
3. Run the port's `tools/build-release.sh` → `server/dist/daoc-server/` (self-contained
   osx-arm64 .NET publish, cmake-built `libDetour.dylib`, ad-hoc codesigning).
   It snapshots the source from `DAOC_SOURCE_REPO`; `daoc server install` pins that
   to the verified `upstream/server/` clone, which is also the default when the
   build script or `fetch-upstream-db.sh` runs on its own. The build also writes
   `defaults/world-sluaghbinder.sqlite`: the Classic classes world plus
   `world/editions/<version>/sluaghbinder.sql` (`daoc dev edition-sql`, ADR 0008).
   `config/edition` picks the world a fresh save starts from.

Prerequisites: .NET 10 SDK, cmake, g++, python3 — all free.

## Server updates and saved progress

`server/dist/daoc-server/` is both the build output and the user's install, so a rebuild
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

- **upgrade**: the result starts as the world of the edition given with
  `--edition=` (else `config/edition`): `defaults/world-sluaghbinder.sqlite` or
  `defaults/world.sqlite`. It receives this server's progress tables and keeps the
  install's settings (population, options, XP rates); the edition is the target's,
  and the Sluaghbinder guard is judged against it.
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

`daoc client install [--wine rosetta|arm64]` installs one of two Wine flavours;
no flag keeps the current one (rosetta when none is recorded). Each has its own
tree and prefix, so both can be installed; the flavour is written to
`dist/.wine-flavour` only after a complete install, and `Checkout` derives the
default `wine_home`/`prefix` from it, on first use: a bad record fails only the
commands that use Wine, and `--wine` replaces it without reading it. Each flavour's
pin records the macOS its binaries are built for as `min_macos`, and install checks
`sw_vers` against the selected flavour's before downloading anything.

1. Wine.
   - **rosetta** (default): verify/fetch athei's wine-build tarball (SHA-256),
     extract to `dist/wine/` (flat `bin/`, `lib/`). It is CrossOver 26.3 Wine with
     i386 support, the x87sidecar Rosetta x87 JIT and mtld3d; its `compatdb.so`
     attaches x87sidecar to every i386 process and picks mtld3d as D3D9.
     Requirements: macOS 26 or later (its `wine`, `wineserver` and `ntdll.so` are
     built with minos 26.0) and Rosetta 2 (probed by running an x86_64 binary).
   - **arm64**: verify/fetch Hadron's release disk image (SHA-256), attach it
     read-only, `ditto` its `runtime/dist` into `dist/wine-arm64/` unchanged, and
     record the image hash in `.daoc-wine.json` (a new pin reinstalls). Upstream
     Wine for arm64 with FEX as its WoW64 (i386) and ARM64EC emulator, and mtld3d.
     Its loader `lib/wine/aarch64-unix/wine.app` is signed with a provisioning
     profile granting Apple's cross-architecture entitlement (memory below 4 GB,
     which a 32-bit program needs); copying keeps that signature valid, so nothing
     in the tree is touched. Requirements: Apple Silicon, macOS 27 or later (its
     `wine`, `wineserver`, `ntdll.so` and loader are built with minos 27.0), no
     Rosetta.
     Security: curl sets no quarantine flag, so Gatekeeper never assesses the
     image or the copied `wine.app` (no notarization or Developer ID check). Trust in
     the runtime rests entirely on the `wine_arm64` SHA-256 pin: review a new pin
     (its release, its source and its signer) as you would new code.
2. Verify/fetch the pinned OfflineDAoC release parts (per-part + archive SHA-256),
   join, extract with zip-slip validation beside `dist/OfflineDAoC`, then swap it
   in, as an update does: an install killed mid-extraction re-runs cleanly.
3. Apply the Client patch to `game.dll` from `game.dll.orig` (byte-verified against
   the recorded pristine hash) on every install: the encryption bypass, and
   clearing `IMAGE_SCN_MEM_SHARED` on the `Shared` section, which an arm64 Wine on
   16 KB pages cannot map at its 4 KB-aligned address. Both flavours run the same
   `game.dll`.
4. Initialize/update the prefix (win10), replace the profile-folder symlinks with
   real directories (no TCC prompt for ~/Documents), copy the client settings from
   another prefix user or the other flavour's prefix when this prefix's user
   (`crossover`, or the macOS user name for arm64) has none, install the launcher
   wrapper. arm64 also copies Hadron's mtld3d into the prefix (native `d3d9.dll` in
   `syswow64`/`system32` plus the `mtld3d.dll` markers) after `wineboot -u`, and runs
   `wine cmd /c exit` to check for "Failed to resolve your host name IP": macOS
   holding the arm64 Wine's Local Network access makes every Wine start wait ~35 s.

Why the rosetta wine: the 1.127 client's game thread spends ~70% of its time in
Rosetta's x87 emulation (libRosettaRuntime) under stock Wine, which caps it at ~7 FPS.
x87sidecar removes that cost; mtld3d replaces wined3d's GL path with Metal.
Why the arm64 wine: Rosetta is general-purpose only through macOS 27. The launch
settings it needs (`client_runtime.ARM64_ENV`: `d3d9=n,b`, FEX disk cache, FEX x87
reduced precision, mtld3d config, large-address-aware) ride on `--env` when `wine_home` has an
`lib/wine/aarch64-unix` (`checkout.wine_is_arm64`, the one arm64 test). Every wine
daoc runs on it, and the Launcher on the same test, gets `DYLD_FALLBACK_LIBRARY_PATH`
to its `ext/lib` (`checkout.wine_env`): without it Wine runs but finds no FreeType
("Wine cannot find the FreeType font library"). The launcher's `DAOC_FPS_OVERLAY=1` shows the Metal
Performance HUD. The evidence behind this, and the other client pitfalls (TCC
prompt, the `crossover` prefix user, the linkdead wait after a kill), is in
`docs/CLIENT-NOTES.md`.

The release ships the original 1.127 Windows client; the patch lets it talk to a
local OpenDAoC server without breaking on the encryption handshake.

## New client

`daoc client install --client new` (`daoc_cli/newclient.py`, ADR 0007) installs the
pinned macOS Godot .NET build (`dist/godot/Godot_mono.app`) and the 0.36c release's
`new-client/godot/` tree into `dist/new-client/godot`: each of the 19 parts is
downloaded, verified, extracted (mtimes kept) into `dist/.new-client.new`, then
deleted, with a done marker per part, and the finished tree is swapped in. The
Windows engine and launcher in the release are skipped. From 0.37 the pin is an
update of 0.36c (`base`): the 0.36c parts go first, then the update's parts, whose
`patch.json` (kept in `downloads/v<version>/` until the swap) lists each replaced
file with the hashes it may replace (`From`, or `absent`) and the one it writes;
every file under `new-client/godot/` is checked against both, an entry it doesn't
list is refused before anything is written, and the finished tree must hold every
file it names. A rerun accepts files already at their new hash.

`daoc client start --client new` runs `open -n Godot_mono.app --args --path
<project> -- --server=127.0.0.1 --account=… --password=…` (`--custom-class=off` on a
Classic classes Game), with `DOTNET_ROOT=~/.dotnet`. The client has port 10300
compiled in, so another port is refused; it has no auto-enter, so the start
succeeds on the login line. Stop and kill find its process by its binary inside
this Checkout's `dist/godot`.

## Client start

`daoc client start` (original client) takes the Game account from the login Keychain (service
`daoc-offline`) and opens `dist/DAoCLauncher.app` with
`wine game.dll 127.0.0.1 <port> 42 <account> <password> [<character> <realm>]`.

- **Keychain**: macOS unlocks the login keychain only for the session you logged
  in to, so in an SSH session `security` reports it locked ("User interaction is
  not allowed", exit 36) rather than the item missing (exit 44). daoc tells the two
  apart. When it's locked and stdin is a terminal, it runs `security unlock-keychain`,
  which asks for the macOS login password itself. With no terminal it stops with
  exit 2 and says how to unlock. It offers to save a new account only when none
  is saved, never after a failed unlock.
- **Character**: `--character NAME` or `DAOC_CHARACTER` (which must exist),
  else the account's most recently played character from the server database.
  With a character, the client logs straight into the world, and a start
  succeeds on a new `WorldInitRequestHandler` line in `server.log`.
- **No character yet**: without the character arguments the client logs in and
  stops at character select. That start succeeds once the server accepts the
  login (`User <account> logging on!`), so the watchdog never kills a client in
  the middle of character creation. The server writes that line before it checks
  the password, so a `Wrong password` after it fails the start at once, with no
  retry.
- **Watchdog**: until the success line appears, a client is hung when its wine
  log has been static for 60 s while the game used under 0.5 s of CPU in 10 s, or
  after 240 s in all. A hung client is killed (only processes mapping this
  checkout's Wine: the selected flavour's, or `DAOC_WINE_HOME`) and relaunched, up to
  `--retries` (default 3).

## Benchmark gate

`daoc client bench` measures the client the player gets, not a synthetic scene:

- **Login** — `daoc client start` with the game account from the login
  Keychain and the character from the server database (`DAOC_CHARACTER`, else the
  most recently played). The game port is the `<Port>` in the server's
  `config/serverconfig.xml`.
- **Play** — the bench drives the character through `sendinput.exe`, a
  mingw-built helper that runs inside the game's own prefix and wineserver, so no
  macOS Accessibility permission is needed. Each cycle `/jump`s to a townsfolk NPC,
  right-clicks it (interact), closes the window and walks a movement pattern.
  `/jump` and `/target` need GM rights: the bench raises a player account to gm
  for the run, records that in `run/bench-gm-raised`, and restores player on exit
  or signal (or at the start of the next run, if the server was gone).
- **Probe** — `client/tools/frametime/ftlog.dylib` (universal: the x86_64 rosetta
  wine and its arm64 x87sidecar, or the arm64 wine, load it) swizzles `-[CAMetalLayer nextDrawable]` and logs
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

`daoc dev e2e` on a clean checkout: install server → boot it on ports
20300/20400, clear of a running server's 10300/10400) → create an account via `daoc-admin` → install client →
launch → pass when the server log shows the login reaching character select and the
client process is still alive ≥120 s later → exit 0. The client runs this
checkout's Wine and prefix (`DAOC_WINE_HOME` / `DAOC_WINEPREFIX` override, as for
the launcher), and that same Wine is what e2e finds and kills it by. Manual UAT
(renders, plays) gates final acceptance after that.

## Server-side notes

Upstream game-logic issues (e.g. character creation with race 21 — HiberniaMinotaur
— throws `KeyNotFoundException` in the server's stat validator) are documented in
`docs/SERVER-NOTES.md`, never patched here.