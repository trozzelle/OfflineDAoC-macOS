# Code review — ported adaptations and install scaffolding

Review pass over the code this repo carries: the client byte-patch script, the
launcher wrapper, the server port overlay, and the install/e2e scripts. Findings
marked **fixed** were corrected during the build; **noted** items are deliberate
and documented here.

## client/apply_game_patch.py — client byte-patcher

- **Fixed** — runs under the stock Xcode CLT Python 3.9 (`from __future__ import
  annotations`; the `Path | None` unions otherwise raise TypeError at import on
  a stock Mac with no pyenv/Homebrew Python).
- **Fixed** — original version hardcoded an absolute home path; now takes the
  DLL path as an argument and the expected pristine hash from the repo's
  `manifest.json` (`client.game_dll_sha256`), passed explicitly by the install
  script. The pin is the single source of truth — `update.sh client` (now
  `daoc client update`) clearing it
  genuinely forces re-derivation.
- **Fixed** — a `.orig` that already exists is trusted as the pristine base (it
  was hash-verified when created); an unpatched DLL with no `.orig` and no pin is
  refused; an already-patched DLL with no `.orig` is reported as "nothing to do"
  rather than an error.
- Verified: output is byte-identical to the client variant that was played and
  confirmed working end-to-end (login → world → combat → quit).

## client/DAoCLauncher.app — Aqua-session wrapper

- **Fixed** — `INSTALL_DIR` counted `../../../..` from the *source* location
  (`client/`), but the installed bundle lives in `dist/`, so the deployed copy
  resolved `dist/dist/OfflineDAoC` and never started the client. The source now
  resolves four levels up, which is correct in both locations.
- **Changed** — the wrapper runs the CrossOver wine from `dist/wine/bin`
  (`DAOC_WINE_HOME` overrides) with mtld3d as D3D9 and x87sidecar attached by the
  wine build's compatdb; wined3d's GL path stays reachable through
  `WINE_COMPATDB`. The Vulkan/DXVK experiment modes from the porting phase
  remain dropped (all failed; see the porting notes in the working-history repo).
- **Fixed** — between relaunch attempts the wrapper runs `wineserver -k` then
  `-w` instead of a fixed 3 s sleep: a lingering wineserver wedged the next
  launch (status=255 or a hang after every crash or kill).
- **Fixed** — `wc -c` on a missing `/tmp/daoc-wine.log` no longer aborts the
  wrapper under `set -e` (`|| true`); `virtual_setup_exception` joins the crash
  signatures.

## server/ — macOS port overlay (vendored from the macOS server port)

- **Noted** — the overlay is the macOS server port's patch series, vendored
  verbatim with attribution: one kqueue-specific source patch
  (`patches/010-adminsockethost-macos-close.patch`), the arm64-safe vendored
  `System.Data.SQLite` (variadic `sqlite3_config` UB fix, dotnet/runtime#48752),
  and the osx-arm64 build/deploy scripts. The upstream repo is untouched; the
  build script snapshots it into `build/src`.
- **Fixed** — `HERE` now resolves via `pwd -P`: MSBuild fails when it sees the
  project graph under two path roots (cloning to a symlinked path such as
  `/tmp` → `/private/tmp` reproduced this).

## install-server.sh (now daoc server install)

- **Fixed** — originally fetched a codeload tarball and verified a recorded
  archive hash; now clones the upstream, checks out the pinned ref, verifies
  `git rev-parse HEAD` against it, and pre-checks every patch with
  `git apply --check` before spending any build time.
- **Fixed** — calls `tools/setup-dotnet.sh` unconditionally (it is idempotent);
  the earlier conditional missed a partial SDK install.
- **Fixed** — a tarball-era `upstream/server` (from the old hash-pinned scheme)
  is detected by the missing `.git` and replaced with a proper clone, so the
  upgrade path from the first layout works.
- **Fixed** — `DAOC_SOURCE_REPO` is exported as the clone verified above, so an
  inherited value cannot point the build at another tree. `build-release.sh` and
  `fetch-upstream-db.sh` default to that same `upstream/server` clone instead of a
  sibling `../daoc-offline-linux-server-bots` checkout.

## install-client.sh (now daoc client install)

- **Fixed** — requirements checks (macOS, Rosetta 2, python3) are explicit and
  fail with actionable messages. Rosetta is probed functionally
  (`arch -x86_64 /usr/bin/true`) rather than by daemon name, which varies across
  macOS versions.
- **Fixed** — `WINEPREFIX` must be absolute (wine rejects a relative path);
  the prefix step now exports `$PWD/$PREFIX`.
- **Fixed** — prefix completion is now verified (`system.reg` exists) after
  `wineserver -w` waits for the hives to flush; the old `|| true` chain could
  silently half-initialize.
- **Fixed** — `winecfg -v win10` removed; it only edits a live prefix and hung
  headless. The `Version` registry key is set via `wine reg add` instead.
- **Changed** — the GStreamer check is gone: the athei/wine-build bundle carries
  its own libraries and plays audio through winecoreaudio.
- **Changed** — every run brings an existing prefix up to the installed wine
  (`wineboot -u`), replaces the prefix users' profile-folder symlinks with real
  directories (the `~/Documents` TCC prompt blocked the client), and copies the
  client settings from a Wine Staging prefix user to `crossover` when `crossover`
  has none (see `docs/CLIENT-NOTES.md`).

## client/fetch_release.py — release fetcher

- **Fixed** — release URL is kept as a string, not a `pathlib.Path` (a Path
  mangles the `//` in URLs).
- **Noted** — mirrors upstream's `Get-OfflineDAoC.ps1` scheme: release manifest
  → per-part SHA-256 → whole-archive SHA-256 → zip-slip-checked extraction,
  with every part hash also pinned in `manifest.json` as a second check.

## e2e-test.sh (now daoc dev e2e)

- **Fixed** — boots the server detached (`nohup … --console`); without a TTY the
  launcher script execs the console in the foreground and dies when the caller's
  pipe closes.
- **Fixed** — seeds `config/` and `data/` from `defaults/` before the port move
  (a fresh install has neither until first start, so the port edit silently
  missed and the server tried the live server's port).
- **Fixed** — creates `logs/` and `run/` before the detached boot (fresh
  installs lack them; the redirect failed and the boot died silently).
- **Fixed** — this install's client is found by the files it maps from this
  install's `dist/wine/` (`lsof`), not by its command line: the CrossOver wine
  shows only `game.dll <args>` as argv. The launcher shell and `start.exe` are
  excluded.
- **Fixed** — the per-attempt process snapshot records pid and executable only;
  the `pgrep -fl` command line it replaced carried the account password into the
  evidence bundle.
- **Fixed** — crash detection uses a seen-flag: only a client that was observed
  running and then vanished counts as a crash, so the spawn window after `open`
  can't produce a false "died".
- **Noted** — 10 launch attempts per run: under the earlier wined3d GL path the
  client crashed roughly half the time before the splash (documented in the
  porting log) and a relaunch succeeded; the budget is kept for the mtld3d build.
  The login-wait window is 180 s per attempt.
- **Noted** — the login check matches `LoginRequestHandler.*User $ACCOUNT
  logging on!` in bytes logged after the launch snapshot only; the aliveness
  window is 120 s on the exact pid from this launch.

## update.sh (now daoc server|client|graphics update and daoc dev ship-pins)

- **Noted** — `update.sh server` (now `daoc server update`) clones the new upstream HEAD into a temp dir
  and runs `git apply --check` over the port patches *before* touching the pin;
  a breaking upstream change leaves the pin untouched and exits non-zero.
- **Noted** — `update.sh client` (now `daoc client update`) clears `game_dll_sha256` on a version bump so
  the patcher cannot silently accept an unknown base; re-deriving the hash is a
  deliberate manual step.

## server/tools/build-release.sh — rebuilds and the release zip

- **Fixed** — rebuilds no longer `rm -rf` the whole `dist/daoc-server/`. They
  delete only `bin/`, `defaults/` and the top-level files listed in `EXTRAS`, and
  refuse while the server runs, so `config/`, `data/`, `logs/` and `run/` survive.
- **Fixed** — the release zip is made with `zip -y`. Without it, `zip` followed
  `bin/config`, `bin/logs` and `bin/navmesh`. That packed the builder's
  `serverconfig.xml` and console logs (account and character names) plus a second
  copy of the navmeshes (709 MB → 89 MB). Users also got real directories in
  place of the links, so their own `config/` edits were ignored.

## server/tools/ProgressImport + deploy/daoc-progress — world upgrade / import

- **Noted** — a port of upstream Offline DAoC's IMPORT PROGRESS engine, with the
  same table policy, verification and rollback. It has no `account.txt` handling,
  keeps account roles, and adds an in-place `upgrade` that keeps the install's settings.
- **Fixed** — an owned house whose lot is missing from the target world used to
  vanish silently while its `DBIndoorItem` rows were still copied. The run now
  aborts before transferring anything and names the houses.
- **Noted** — the `ItemTemplate` merge is deliberately unfiltered: every old
  template the world lacks is kept, because `Inventory`, `househookpointitem` and
  `CharacterXOneTimeDrop` all reference templates. The world's definition wins on
  an ID collision.
- **Fixed** — the undo steps (README and usage text) say to delete a leftover
  `-wal`/`-shm` before copying a backup back. SQLite would otherwise replay
  another database's WAL into the restored file.
- **Fixed** — the wrapper's own running-server check is gone. It blocked the
  read-only `inspect` and the usage text, and the engine already refuses
  `upgrade` and `import` while this server or the source save's server runs.

## client/tools and the benchmark

- **Noted** — the game account lives only in the login Keychain (service
  `daoc-offline`). On first use `launch-client.sh` (now `daoc client login`) reads the account name and lets
  `security add-generic-password -w` prompt for the password itself, so it is
  neither echoed nor on a command line; without a TTY it aborts instead of asking.
- **Noted** — database lookups (character for the launch, character position and
  NPC for the bench's movement check) open the server DB read-only with
  parameterized queries.
- **Noted** — teardown is scoped to this install: `kill-client.sh` (now `daoc client kill`) signals only
  this bundle's launcher and the `game.dll`/x87sidecar processes mapping files from
  this install's wine, so another checkout's client is never touched. Scripts call
  `/bin/ps`, `/usr/bin/pgrep` and `/usr/sbin/lsof` by absolute path (a shell
  builtin `ps` misreported the translated client's CPU).
- **Noted** — `launch-client.sh` (now `daoc client start`) counts a login only on a new
  `WorldInitRequestHandler` line: the server logs `LoginRequestHandler` even for a
  login refused because the character is still linkdead.
- **Noted** — `bench-run.sh` (now `daoc client bench`) writes its output to a `mktemp -d` directory
  (`DAOC_BENCH_OUT` overrides) and restores the account role on exit and on
  INT/TERM/HUP; a marker file in the server's `run/` carries an unfinished restore
  to the next run.

## Known limitations

- The server port targets osx-arm64 only (the port's .NET runtime and native
  libraries are arm64-only); Intel Macs are unsupported.
- The fresh-clone e2e seeds the download cache from a local copy to avoid
  re-downloading ~5 GB; on a truly cold machine the same flow runs from the
  network (verified per-piece against the release manifest).