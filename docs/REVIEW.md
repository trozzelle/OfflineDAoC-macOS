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
  script. The pin is the single source of truth — `update.sh client` clearing it
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
- **Noted** — the wrapper only supports the proven GL mode; the Vulkan/DXVK
  experiment modes from the porting phase were deliberately dropped (all failed;
  see the porting notes in the working-history repo).

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

## install-server.sh

- **Fixed** — originally fetched a codeload tarball and verified a recorded
  archive hash; now clones the upstream, checks out the pinned ref, verifies
  `git rev-parse HEAD` against it, and pre-checks every patch with
  `git apply --check` before spending any build time.
- **Fixed** — calls `tools/setup-dotnet.sh` unconditionally (it is idempotent);
  the earlier conditional missed a partial SDK install.
- **Fixed** — a tarball-era `upstream/server` (from the old hash-pinned scheme)
  is detected by the missing `.git` and replaced with a proper clone, so the
  upgrade path from the first layout works.

## install-client.sh

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
- **Noted** — GStreamer framework is optional (warned, not enforced): the
  verified working configuration ran without it.

## client/fetch_release.py — release fetcher

- **Fixed** — release URL is kept as a string, not a `pathlib.Path` (a Path
  mangles the `//` in URLs).
- **Noted** — mirrors upstream's `Get-OfflineDAoC.ps1` scheme: release manifest
  → per-part SHA-256 → whole-archive SHA-256 → zip-slip-checked extraction,
  with every part hash also pinned in `manifest.json` as a second check.

## e2e-test.sh

- **Fixed** — boots the server detached (`nohup … --console`); without a TTY the
  launcher script execs the console in the foreground and dies when the caller's
  pipe closes.
- **Fixed** — seeds `config/` and `data/` from `defaults/` before the port move
  (a fresh install has neither until first start, so the port edit silently
  missed and the server tried the live server's port).
- **Fixed** — creates `logs/` and `run/` before the detached boot (fresh
  installs lack them; the redirect failed and the boot died silently).
- **Fixed** — the client-process pattern is derived from the install path
  (`$(basename "$PWD").dist.OfflineDAoC…`); a hardcoded repo name matched
  nothing in a differently named clone and misread every launch as a crash.
- **Fixed** — crash detection uses a seen-flag: only a client that was observed
  running and then vanished counts as a crash, so the spawn window after `open`
  can't produce a false "died".
- **Noted** — 5 launch attempts per run: the client's wined3d GL init under
  Rosetta crashes roughly half the time before the splash (documented in the
  porting log); a relaunch succeeds. The login-wait window is 180 s per attempt
  (login takes 1–2 minutes per the runbook).
- **Noted** — the login check matches `LoginRequestHandler.*User $ACCOUNT
  logging on!` in bytes logged after the launch snapshot only; the aliveness
  window is 120 s on the exact pid from this launch.

## update.sh

- **Noted** — `update.sh server` clones the new upstream HEAD into a temp dir
  and runs `git apply --check` over the port patches *before* touching the pin;
  a breaking upstream change leaves the pin untouched and exits non-zero.
- **Noted** — `update.sh client` clears `game_dll_sha256` on a version bump so
  the patcher cannot silently accept an unknown base; re-deriving the hash is a
  deliberate manual step.

## Known limitations

- The server port targets osx-arm64 only (the port's .NET runtime and native
  libraries are arm64-only); Intel Macs are unsupported.
- The fresh-clone e2e seeds the download cache from a local copy to avoid
  re-downloading ~5 GB; on a truly cold machine the same flow runs from the
  network (verified per-piece against the release manifest).