# Session state (break point, 2026-10-10 ~09:20) — CORRECTED

## Where we are
- Goal: 60+ FPS for OfflineDAoC client on macOS (M5 Ultra). Pass bar: avg≥60 FPS AND p95≤16.7 ms over scripted 5-min moving run.
- Clean baseline (moving, 300 s drive window): **wall-FPS 30.8**; presented frames avg 33.0 FPS (30.3 ms), p95 64.1 ms (15.6 FPS); 36.9% of frames ≤16.7 ms; 19.7 s of present gaps in 300 s.
- The earlier "11.5 FPS" reading was **OS throttling** (App Nap / occlusion / no caffeinate), not rendering. After `NSAppSleepDisabled`, frontmost window, and `caffeinate`, the same setup read ~57 FPS presented (17.6 ms) in the 60 s validation. The 60 s gate needs a full 5-min run; p95 20.8 ms was still over target in that short pass.
- The final 300 s baseline above was measured WITH those preconditions but WITHOUT re-verifying frontmost — treat 30.8 vs 57 as unexplained variance to resolve (coverage gaps of 19.7 s suggest stalls remain).

## Root causes established
- `showFPS=1` registry value caused the pre-login HANGS (every launch after ~08:15 hung; deleted → logins worked again). It did NOT cause low FPS.
- The renderer is **wined3d-GL** (`wined3d_adapter_gl_init`, `wined3d_guess_gl_vendor` in every log; bundled MoltenVK instance creation is just Wine's Vulkan probe). NOT the Vulkan backend. So `WINE_D3D_CONFIG=renderer=gl` is a no-op — the current baseline IS GL. `MVK_CONFIG_*` variables only matter for the DXVK arm.
- There is no wined3d FPS overlay to read; the **frametime trace is the measurement** (`WINEDEBUG=trace+frametime` → `Frame duration NNN μs` per present in `/tmp/daoc-wine.log`).
- Input: **vkey events don't move the character; scancodes do** (DirectInput). `sendinput.exe sc <hex> down/up/hold` works — verified by scene change.

## Harness (all in daoc-macos/client/)
- `input-helper/sendinput.exe` — wine-internal SendInput helper (mingw-built). Usage: `sendinput sc <sc-hex> down|up [hold-ms]`, `sendinput vk ...`, `sendinput click x y [ms]`, `sendinput type <text>`.
- `bench-drive.sh <sec>` — movement pattern (W holds + arrow turns + unstick). NOTE: arrows may need `KEYEVENTF_EXTENDEDKEY` (E0-prefixed scancodes) — turning is unproven; compass stayed NE through the whole run. DAoC default turn keys may be A/D instead.
- `bench-run.sh <sec> <out.csv>` — full cycle: clean state → launch (quick-login args `game.dll 127.0.0.1 20300 42 $ACCT $PW Ada 3`, credentials from Keychain) → wait world entry → settle 45 s → drive + 2 s sampler (`(unixtime, frame-count)` → `<out>.sampler`) → done. Analysis is an inline python script (in transcript; re-derive from sampler + winelog).
- Movement proof so far is qualitative (scene changed). Advisor suggests numeric `/loc` diff: type `/loc`+Enter via `sendinput type`, read coords from chat via vision, hold W, `/loc` again. Also serves as the per-run "movement happened" assertion.

## Key facts
- Client: 32-bit (PE32 i386) `game.dll`; Wine Staging 11.18 x86_64 under Rosetta 2; syswow64 d3d9.dll is the one that loads.
- Server: `daoc-macos/server/dist/daoc-server` (ports **20300**/20400), account `macadmin` (character **Ada**, realm 3 Hibernia), 30 bots, population ON.
- Launcher (both `dist/DAoCLauncher.app` and source `client/DAoCLauncher.app` copies) now honors `DAOC_DLL_OVERRIDES` env (default `d3d9,dxgi=b` = builtin wined3d). This edit is uncommitted and must be part of the final patch.
- Known flaky: wined3d GL-caps probe crashes ~50% of launches (relaunch fixes; launcher auto-retries). A killed client leaves the player linkdead 60 s — **wait for `macadmin just disconnected` in the server log (bytes after the kill) before relaunching**, or the next login hangs.
- Porting-log prior art on DXVK (read `docs/PORTING-LOG.md` ~lines 130-190 before the DXVK arm): bundled MoltenVK 1.4.0 fails swapchain creation (MTLTEXTURE external memory); DYLD_LIBRARY_PATH MoltenVK 1.4.3 injection crashed wine; DXVK needs the `wine-vulkan-portability.patch` on win32u unless the Gcenx build already has it; DXVK-macOS PR #20 de-aliased samplers is what the staged `dxvk.conf` configures.

## Global/leftover state (disclosed)
- `defaults write org.winehq.wine-staging.wine NSAppSleepDisabled -bool YES` — global user default (survives; candidate to move into the launcher/Info.plist as `LSAppNapIsDisabled` for the patch).
- `caffeinate -dimsu` was started but has since exited; NOT running now. The launcher patch should own this (`caffeinate -i -w <pid>` or Info.plist).
- DXVK d3d9/dxgi staged in `dist/dxvk/`; prefix d3d9 restored from `d3d9.dll.wine-bak` (builtin). The earlier 6-crash streak was the no-window-server signature (harness shell launch, not DXVK).
- Client idle in-world right now (optional: `/quit` it cleanly before long pauses).

## Next steps
1. Stabilize the measurement: assert per-run which renderer loaded (GL vendor line present; no DXVK `d3d9.log`), use `+timestamp` or sampler alignment, compute stats over the drive window only, and resolve the 30.8-vs-57 variance (frontmost + App Nap state per run).
2. Numeric movement proof: `/loc` before/after a W hold (also proves typed input for NPC interaction later).
3. DXVK arm: copy `dist/dxvk/d3d9.dll` (i386) into syswow64, `DAOC_DLL_OVERRIDES='d3d9,dxgi=n'`, `DXVK_LOG_LEVEL=info`, expect the documented swapchain failure; check win32u portability patch first.
4. Fix turning (extended-key scancodes or A/D), then the full 5-min gate run.
5. If DXVK fails again: d9mt (D3D9→Metal direct), or wine build with newer MoltenVK.
## AFTERNOON UPDATE (2026-10-10 ~13:16)
- The 7 FPS stall is NOT: day/night cycle (daylight tested at 7:42 am — still 7 FPS), GPU contention from the ML servers (probe showed util 0% at 7 FPS), or scene content (simple terrain, 80% flat grass).
- STILL UNTESTED: (a) the client's inactive/background throttle — every capture showed Terminal as the active app, and the wine click cannot raise the game window at the macOS level; the helper must call SetForegroundWindow on the game's own HWND (activate.exe needs fixing: enumerate ALL top-level windows and match the game's, not its own pid); (b) weather — the server logs RegionWeather storms for region 200 (Hibernia); grep `RegionWeather Region=200` against the FPS phase changes, and a GM `/weather` command may exist in the source for a clean A/B.
- The stall IS: uniform ~86ms frame floor, wined3d_cs parked in an ntdll wait, GPU 0% during the stall, 3% client CPU. A present/pacing lock INSIDE the client/wine, not outside.
- The 08:45 clean validation hit 57 FPS presented (17.6ms frames) — the stack CAN do it. Something about that session differed and we haven't isolated it yet. Best remaining suspects: (a) a wine-level timer/scheduling difference (msync not present in this build?), (b) the game's own background/inactive throttle misbehaving, (c) some transient macOS window-server state.
- macadmin is now server-role admin (needed for /time). The in-game chat accepts scancode-typed commands (Enter opens chat; type via scancodes; Enter submits). /time <speed> <time> resets the cycle (my scancode args failed — VK-vs-scancode mismatch, needs fixing if we need it again).
- DISCLOSED SYSTEM CHANGES: macadmin's server role is now `admin` (was `player` — revert to `player` before final delivery); global `defaults write org.winehq.wine-staging.wine NSAppSleepDisabled -bool YES` is still set; Game Mode policy restored to `auto`; `client/x87sidecar/` clone is gitignored; caffeinate and watch loops are NOT running (checked 13:20).
- x87sidecar built and --probe PASSES on this Rosetta, but cooperative attach needs a patched wine (athei/wine branch); entitled attach needs a one-time dev-tools password.
- HARNESS FIX NEEDED: bench-run.sh's hang-retry loop had a logic bug (killed healthy launching clients) — current version cycles launches but the launch flake rate today was high (6 crashes in a row at 12:19). A launch-client.sh with absolute paths + 30s login watchdog + auto-sample is the next harness improvement.

## WEATHER CORRELATION (13:20)
- Region-200 storms: 07:52 (737s→08:04), 11:26 (3405s→12:23), 12:37 (1920s→13:10), 13:13 (1343s→13:36).
- The 08:45 57-FPS validation ran storm-free; the 12:39-13:10 7 FPS phase ran inside the 12:37 storm. BUT the 13:10-13:13 readings (storm-free gap) were still 7 FPS — weather doesn't cleanly explain it either. Keep weather as a secondary suspect (intensity 109 storm active NOW); the client's focus/inactive throttle remains the top untested lead.
- Client died at 13:18:02 (status=1, 1201s in-world, clean exit — no crash signature).

## TIER-1 A/B RESULTS (2026-10-10 ~20:30)
- ACTIVATION: activate.exe fixed (now finds the game's own HWND by largest-window + title match, "Dark Age of Camelot © 2001-2021 EA"). Wine-level activation succeeded — still 7 FPS. The wine process registers as type="BackgroundOnly" so macOS will never make it frontmost; AppleScript can't reach it. RULED OUT (wine level). macOS-level frontmost remains impossible for this process type.
- OCCLUSION: DEFINITIVELY RULED OUT — same client measured 322 frames/45s with desktop cluttered vs 324 frames/45s with the game window fully visible.
- WINE_D3D_CONFIG=csmt=0 → client hangs at wined3d init. renderer=gdi → hangs at init. Both dead on this build.
- caffeinate -i (App Nap idle prevention) → still 7 FPS. RULED OUT.
- Frame duration semantics CONFIRMED via wine source (dlls/wined3d/cs.c:742-752): present-to-present wall time via QueryPerformanceCounter. Values are real. Current stall: 137.9ms avg (measured wall 7.26 vs presented 7.3 — metrics now AGREE; the 08:45 30-vs-57 discrepancy was a sampling artifact, true rate was ~57).
- LAUNCHER HARDENED: crash signature list now includes virtual_setup_exception (both copies); relaunch path now runs wineserver -k + -w (|| true for set -e) instead of sleep 3; client/tools/launch-client.sh has a hang watchdog (log static 30s + no login → kill tree, retry). Watchdog proved itself: 3 hung attempts auto-killed, 4th logged in.
- `sample` of the live 7 FPS client: wined3d_cs thread 88% parked at ntdll.so+0x30b55 (wine's generic wait thunk under Rosetta — no symbolization possible without wine debug symbols). No game.dll/d3d9 frames visible in any thread.
- NEXT: mhmdrz/wine v11 (wine-crossover-x86_64-macos, msync + D3DMetal ported) downloading for the msync A/B. Fallback candidates: dttdrv/wiage (Wine 11.13 + CrossOver 26.2 msync), marzent/wine-msync (patches only).

## ROOT CAUSE FOUND + FIX (2026-10-10 ~21:25)
- 7 FPS = CPU-bound game thread in **Rosetta x87 emulation**, not a wait. `ps`/aliased `top` misreport CPU for this process (2.9%); `/usr/bin/top` = 123%, `ps -M` = one thread at 100%. `sample` top-of-stack: 71% of active samples in libRosettaRuntime (0x208014000-0x20807c000, vmmap). Page faults ~1/s → not SMC. Population off → no change; fresh server → no change.
- FIX: athei/wine-build `cx-26.3.0-8` (CrossOver 26.3 / wine-11.0, i386 + bundled x87sidecar v1.8.0, cooperative attach, no password) staged in `dist/x87/` (wine/, Wine.app shim → wine, prefix/ = APFS clone of dist/prefix, wineboot -u'd). `x87sidecar --probe` = supported.
- RESULT (standing in-world, wined3d d3d9 forced via WINE_COMPATDB): **59.1 FPS, avg 16.9 ms, p50 15.6, p95 27.8, p99 30.5** (vs 7.3 FPS / 137.8 ms baseline). 8x.
- GOTCHAS: (1) cx wine binary triggers a TCC "wine would like to access Documents" prompt → game blocks at 0% CPU pre-window (looked like a hang). Fix: replace prefix `drive_c/users/*/{Documents,Desktop,...}` symlinks with real dirs. (2) cx wine's Windows user is `crossover`, not `ada`: game settings live in `users/crossover/AppData/Roaming/Electronic Arts/...` (copied from ada). (3) cx defaults d3d9 to mtld3d (D3D9→Metal); `WINE_COMPATDB=$'v=5\nname=daoc;exe=game.dll;d3d9=wined3d'` forces wined3d.
- HARNESS: launch-client.sh now forwards WINE_COMPATDB/ROSETTA_X87_PATH/X87_* when set, DAOC_WINEPREFIX passthrough fixed, hang = log static 60s AND game cpu <1%, timeout path now kills the tree, kill_tree kills the .app relaunch loop first (cause of duplicate wine instances).
- Server now run by the agent: `cd server/dist/daoc-server/bin && nohup ./CoreServer --start -config=.../config/serverconfig.xml` (pid in run/server.pid, log logs/console.out + logs/server.log).

## GATE RESULTS + PRODUCTIZED (2026-10-10 ~22:15) — branch perf/x87sidecar
- 5-min gates (probe = per-present CAMetalLayer timestamps, client/tools/frametime): wined3d+x87 71.7 FPS, p95 21.5 ms (FAIL); **mtld3d+x87 (cx default) 119.6 FPS, p95 10.1 ms (PASS, movement only)**; final `client/bench-run.sh` with NPC interaction (/jump + /target + right-click merchant → trade window) + movement in Ardee: **90.6 FPS, p95 14.57, p99 17.7, 1%-low 39.5, vsync off maxFps 0, PASS**.
- Metal HUD system-log logging produced no lines (MTL_HUD_LOGGING_ENABLED); HUD overlay itself works over mtld3d (DAOC_FPS_OVERLAY=1). HUD over wined3d-GL broke presentation (0 frames). HUD runs raised a Documents TCC prompt even with the prefix sandboxed.
- Dev tree now uses the shipped layout: dist/wine = cx build (flat), dist/prefix = cx prefix. Old Staging wine+prefix moved to dist/staging-backup/ (not deleted).
- macadmin role reverted to `player`; bench-run.sh raises to gm for the run and restores.
- Patch: /Users/ada/development/games/daoc-macos-x87-perf.patch = `git diff cbd3301..HEAD`. Fresh-clone verification in /Users/ada/development/games/daoc-verify.

## END-STATE VERIFIED (2026-10-10 ~22:36)
- Fresh `git clone` of trozzelle/OfflineDAoC-macOS at cbd3301 (/Users/ada/development/games/daoc-verify) → `git apply --check` + apply of the final patch → `install-server.sh` (0 errors; 599 C# + 1 C++ warnings, all upstream) + `install-client.sh` (downloads/ seeded by APFS clone, SHA-verified) → server started from that tree with a copy of the dev world DB → that tree's `client/bench-run.sh 300`: **104.8 FPS avg, p95 11.97 ms, p99 13.07, 1%-low 63.2, vsync off maxFps 0, 8 NPC interaction cycles, moved 849 units — PASS**.
- DAOC_FPS_OVERLAY=1 verified from the fresh tree: HUD shows 86.86 FPS / 11.51 ms frame interval (agrees with the probe).
- Bugs found only on the fresh tree, fixed: `grep -c … || echo 0` gave "0\n0" on a server log with no world entries (launch-client never saw world entry); a server started from the agent's tool shell died silently ~1 min later (start it from a Terminal/.command or launchd, never the agent shell). bench-run now fails INVALID if the server is down after the play window.
