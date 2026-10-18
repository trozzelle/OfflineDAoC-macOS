# OfflineDAoC server — macOS port

A macOS (Apple Silicon) build of the [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots)
DAoC server: one portable folder, no .NET install needed, with the Classic + Shrouded Isles
world, autonomous gamebots, and the admin TUI/CLI.

The Linux repo is the **read-only parity baseline**. This repo contains only the macOS-specific
build pipeline, launcher scripts and documentation; the server source itself is compiled from a
snapshot of the pinned Linux repo clone (`upstream/server`, made by `daoc server install`) with
macOS patches from `patches/`.

## Requirements

- macOS on Apple Silicon (arm64). Intel Macs are not covered by this port (the .NET runtime
  and native libraries here are arm64-only).
- Build-time only: Xcode Command Line Tools (`xcode-select --install`), cmake
  (`brew install cmake`), and the .NET 10 SDK (installed automatically into `~/.dotnet` by
  `tools/setup-dotnet.sh` if missing). Internet for the first build.
- Run-time: nothing else. The server bundles its own .NET runtime and uses the macOS system
  libsqlite3; there is no SQLite.Interop dependency (see "SQLite on arm64" below).

## Quick start

```bash
daoc server install            # from the checkout: the selected game version's build (see ../README.md)
cd dist/daoc-server
./daoc-server.sh start         # server in the background + admin screen in this terminal
```

- `./daoc-server.sh stop` stops the server (saves first).
- `./daoc-admin` reopens the admin screen later; `./daoc-admin help` lists CLI commands.
- The world and all saves live in `data/opendaoc.sqlite3.db`; config in `config/` — both are
  yours and are kept on upgrade. A release with new world data needs `./daoc-progress upgrade`
  to move your progress into it (see Maintenance). The folder layout, commands and admin screens
  are identical to the Linux repo's `docs/RUN.md`; that guide applies here verbatim.

## What differs from the Linux repo

| Area | Linux repo | This port |
|---|---|---|
| Target | linux-x64, glibc 2.34+ | osx-arm64 |
| Native pathing library | `bin/lib/Detour.so` | `bin/lib/Detour.dylib` |
| SQLite | NuGet `System.Data.SQLite.Core` + `SQLite.Interop.dll` (hashed exports) | Same package's managed assembly **replaced** by the vendored project source compiled with `SQLITE_STANDARD`, binding the macOS system `libsqlite3` |
| Source | built in place | built from a snapshot copy in `build/src` with `patches/*.patch` applied (the reference repo stays untouched) |
| Build box | distrobox (Ubuntu 22.04) | Native macOS toolchain |
| Release archive | `.tar.gz` | `.zip` |
| Install scripts | `tools/build-release.sh`, `deploy/*` | macOS equivalents in `tools/` and `deploy/` |
| World upgrade / progress import | none | `daoc-progress`: Offline DAoC's IMPORT PROGRESS engine, ported (see Maintenance) |

### SQLite on arm64

The NuGet package ships prebuilt native `SQLite.Interop` binaries for win-x86/x64, linux-x64
and osx-x64 — there is no osx-arm64 build, and its interop exports hashed symbol names (`SI0…`)
that cannot be reproduced from the public source. Worse, a `SQLITE_STANDARD` (system-library)
build of System.Data.SQLite crashes on arm64: the managed code calls the variadic
`sqlite3_config` through fixed-argument P/Invoke declarations, which is undefined behaviour on
Apple Silicon (variadic arguments are read from the stack save area, which a fixed-arg caller
never writes; see dotnet/runtime#48752). The vendored source in `vendor/System.Data.SQLite`
therefore carries two small patches (`SQLite3.cs`: `StaticSetMemoryStatus` and `SetLogCallback`
become no-ops) so that no variadic `sqlite3_config` call is ever made; SQLite keeps its
defaults and the server's own NLog stack does all logging.

`tools/build-release.sh` compiles the vendored source (with `SQLITE_STANDARD`) and overlays the
resulting `System.Data.SQLite.dll` onto the server, DaocAdmin and WorldBuilder outputs so no
output ever binds `SQLite.Interop.dll`.

### Admin socket close (macOS)

Closing the admin Unix-domain socket while its asynchronous accept is pending does not wake the
blocked accept on macOS (kqueue-based .NET), leaving `ServerStopped` stuck in a spin-wait
forever. `patches/<version>/010-adminsockethost-macos-close.patch` (the file moved to `src/Admin.Host/` in
the 0.36 sync; the hunk is the same) connects a dummy client to wake the
pending accept before the listener is disposed. Verified: clean stop in ~3 s with bots in the
world (the Linux reference stops in ~2 s).

### Login logging (0.36)

In the 0.36 sync the admin module moved into its own project, and `CoreServer` registers it
(`AdminHost.Register()`) before `GameServer.CreateInstance()` initialises logging. That first touch
of `LoginRequestHandler` creates its static logger as a `NullLogger`, so no `User … logging on!`
line ever reaches `server.log`, and `daoc client start` and `daoc dev e2e` wait for that line.
`patches/0.36/020-loginrequesthandler-lazy-logger.patch` creates the logger on first use instead.
Without it the login is still accepted (the account's `LastLogin` updates); only the line is
missing.

## Layout

```
tools/build-release.sh       builds the portable server folder (from the Linux repo's sources)
tools/setup-dotnet.sh        one-time .NET 10 SDK installer
tools/fetch-upstream-db.sh   unpacks/verifies the pinned OpenDAoC-Database dump
deploy/daoc-server.sh        start/stop/status (equivalent of the Linux launcher)
deploy/daoc-admin            admin TUI/CLI wrapper
deploy/daoc-progress         world upgrade / progress import wrapper (macOS port addition)
tools/ProgressImport/        daoc-progress source: upstream Offline DAoC's progress importer, ported
deploy/navmesh-install.sh    navmesh installer (macOS port): --from-xz <world/navmesh>, --from-dir
patches/<version>/*.patch    macOS patches applied to that game version's source snapshot
world/editions/<version>/    the Sluaghbinder world overlay (daoc dev edition-sql)
vendor/System.Data.SQLite    vendored System.Data.SQLite 1.0.119 source + arm64 patches
build/src                    snapshot of the reference repo's source (created by the build)
dist/                        build output (gitignored)
```

## Maintenance

- **Backup**: stop the server, copy `data/opendaoc.sqlite3.db` (or use
  `sqlite3 data/opendaoc.sqlite3.db ".backup backup.db"` while running — WAL-safe).
- **Upgrade**: rerun `daoc server install` (it runs `tools/build-release.sh` with
  `DAOC_GAME_VERSION` and `DAOC_NAVMESH_SRC` set); it replaces `bin/`, `defaults/` and the scripts
  and keeps `config/`, `data/`, `logs/` and `navmesh/` (it refuses while the server is running).
- **Editions**: `defaults/world.sqlite` is the Classic classes world, and
  `defaults/world-sluaghbinder.sqlite` the same world with the Sluaghbinder (its trainer, wisp
  and class rows, `enable_sluaghbinder = True`). `config/edition` (`sluaghbinder` or `classic`,
  written by `daoc`) picks the one a fresh save starts from.
- **New world data** (a release whose world changed, e.g. the 0.36 sync): an existing `data/`
  keeps the world it was created with. With the server stopped, `./daoc-progress upgrade
  [--edition=sluaghbinder|--edition=classic]` moves your progress into the new world of that
  edition (default: `config/edition`): accounts (roles kept), characters, items, money, houses,
  guilds and bots, plus this install's settings (population, `daoc-admin options`, XP rates).
  The edition is the one given; a save with Sluaghbinder characters cannot move into the
  Classic classes world. `./daoc-progress inspect <folder> --json` prints the counts. World state such as keep and relic ownership
  starts fresh. The previous save is backed up to `data/progress-backups/<time>/` with an
  `import-report.txt`; to undo, stop the server, delete `data/opendaoc.sqlite3.db-wal` and
  `data/opendaoc.sqlite3.db-shm` if they exist (SQLite would replay a leftover `-wal` into the
  restored file), then copy that `opendaoc.sqlite3.db` back to `data/`. `upgrade` and `import`
  refuse, changing nothing, when an owned house's lot is missing from the world they move into.
- **Bring a save from elsewhere**: `./daoc-progress import <folder> --replace-progress` replaces
  this server's progress with another save's (an older server folder, or a Windows Offline DAoC
  folder containing `runtime/`); this server keeps its world and settings, and the source is only
  read (it is copied first, so its folder is never written to). `./daoc-progress inspect <folder>`
  shows what a save holds. This is upstream's IMPORT
  PROGRESS engine (same table policy and verification) without its `account.txt` handling and
  without resetting account roles. Tested on this port's own saves; for Windows folders only the
  `runtime/` lookup has been tested (with a release that had no progress yet), so keep the
  Windows original until you've checked the imported characters in game.
- **Clean rebuild**: delete `build/` and rerun the build; it re-syncs the snapshot from the
  reference repo (`DAOC_SOURCE_REPO` overrides the reference path, default `upstream/server` in the
  repo root). Don't delete `dist/daoc-server/`: it is your install (`data/` holds every save,
  `config/` your settings), and rebuilding over it is safe.

## Known limitations

- The navmesh generator (`tools/navmesh`) and `navmesh-install.sh --build-from-client` remain
  Windows/Wine-only, exactly as in the Linux repo.
- No client is included; point a DAoC client at TCP 10300 (UDP 10400) as documented in the
  Linux repo's `docs/RUN.md`.
- Intel Macs are untested/unsupported by this port.