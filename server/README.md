# OfflineDAoC server — macOS port

A macOS (Apple Silicon) build of the [daoc-offline-linux-server-bots](https://github.com/catastrophic-impact/daoc-offline-linux-server-bots)
DAoC server: one portable folder, no .NET install needed, with the Classic + Shrouded Isles
world, autonomous gamebots, and the admin TUI/CLI.

The Linux repo is the **read-only parity baseline**. This repo contains only the macOS-specific
build pipeline, launcher scripts and documentation; the server source itself is compiled from a
snapshot of the pinned Linux repo clone (`upstream/server`, made by `install-server.sh`) with
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
tools/setup-dotnet.sh          # installs the .NET 10 SDK into ~/.dotnet if missing
tools/build-release.sh         # builds dist/daoc-server/ and the release zip (~2 min after first run)
cd dist/daoc-server
./daoc-server.sh start         # server in the background + admin screen in this terminal
```

- `./daoc-server.sh stop` stops the server (saves first).
- `./daoc-admin` reopens the admin screen later; `./daoc-admin help` lists CLI commands.
- The world and all saves live in `data/opendaoc.sqlite3.db`; config in `config/` — both are
  yours and are kept on upgrade. The folder layout, commands and admin screens are identical to
  the Linux repo's `docs/RUN.md`; that guide applies here verbatim.

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
forever. `patches/010-adminsockethost-macos-close.patch` connects a dummy client to wake the
pending accept before the listener is disposed. Verified: clean stop in ~3 s with bots in the
world (the Linux reference stops in ~2 s).

## Layout

```
tools/build-release.sh       builds the portable server folder (from the Linux repo's sources)
tools/setup-dotnet.sh        one-time .NET 10 SDK installer
tools/fetch-upstream-db.sh   unpacks/verifies the pinned OpenDAoC-Database dump
deploy/daoc-server.sh        start/stop/status (equivalent of the Linux launcher)
deploy/daoc-admin            admin TUI/CLI wrapper
deploy/navmesh-install.sh    navmesh installer (macOS port)
patches/*.patch              macOS patches applied to the source snapshot
vendor/System.Data.SQLite    vendored System.Data.SQLite 1.0.119 source + arm64 patches
build/src                    snapshot of the reference repo's source (created by the build)
dist/                        build output (gitignored)
```

## Maintenance

- **Backup**: stop the server, copy `data/opendaoc.sqlite3.db` (or use
  `sqlite3 data/opendaoc.sqlite3.db ".backup backup.db"` while running — WAL-safe).
- **Upgrade**: rerun `tools/build-release.sh`; it replaces `bin/`, `defaults/` and the scripts
  and keeps `config/`, `data/` and `navmesh/`.
- **Clean rebuild**: delete `build/` and `dist/`; the build re-syncs the snapshot from the
  reference repo (`DAOC_SOURCE_REPO` overrides the reference path, default `upstream/server` in the
  repo root).

## Known limitations

- The navmesh generator (`tools/navmesh`) and `navmesh-install.sh --build-from-client` remain
  Windows/Wine-only, exactly as in the Linux repo.
- No client is included; point a DAoC client at TCP 10300 (UDP 10400) as documented in the
  Linux repo's `docs/RUN.md`.
- Intel Macs are untested/unsupported by this port.