# Client-side notes

Findings about running the 1.127 client under Wine on Apple silicon that shaped
the install and the scripts. Each one cost a long investigation; read this before
changing the wine build, the prefix setup, or the launch/stop scripts.

## ~7 FPS under stock Wine is Rosetta's x87 emulation

Under a Wine without x87sidecar the client runs at ~7 FPS (≈138 ms per frame)
no matter what is on screen. The game thread is CPU-bound:

- `ps -M` shows one thread at 100%; `/bin/ps` and `/usr/bin/top` show the client
  at ~119% CPU. Use Apple's `/bin/ps` by absolute path: a shell builtin `ps`
  reported ~3% for the translated process and made the stall look like a wait.
- `sample` of the running client: ~71% of active samples sit in
  `libRosettaRuntime` (the address range from `vmmap`), i.e. Rosetta emulating
  the game's x87 floating point. Page faults stay around 1/s, so it is not
  self-modifying-code churn.
- The wined3d command-stream thread is parked in an ntdll wait during the stall:
  it is waiting on the game thread, not the cause.
- Ruled out (no change in frame rate): server population on/off, a fresh server,
  window occlusion, App Nap (`caffeinate -i`, `NSAppSleepDisabled`), wine-level
  window activation, in-game weather and time of day.

Fix: athei's wine-build (CrossOver 26.3 Wine) with the bundled x87sidecar, which
runs the x87 code as native ARM64, and mtld3d (D3D9 on Metal). Under that build the
5-minute bench (NPC interaction plus movement) measured 90–105 FPS average with
p95 12–15 ms.
x87sidecar's cooperative attach needs a wine built for it; the standalone sidecar
against another wine needs an entitled attach (a one-time developer-tools password).

## The TCC prompt for ~/Documents blocks the client

Wine links each prefix user's Windows profile folders (Documents, Desktop, ...)
to the macOS home folders. The first time the client touches `~/Documents`, macOS
raises a privacy (TCC) prompt for the wine binary, and the client blocks at 0% CPU
before its window appears until the prompt is answered — it looks like a hang,
and the prompt is easy to miss behind other windows. `install-client.sh` replaces
those symlinks with real directories inside the prefix, so the prompt never
appears. Runs with the Metal Performance HUD (`DAOC_FPS_OVERLAY=1`) have still
raised a Documents prompt once with the prefix set up this way.

## The prefix's Windows user is `crossover`

The CrossOver wine names its Windows user `crossover`, not the macOS user name.
The client's settings live in
`dist/prefix/drive_c/users/crossover/AppData/Roaming/Electronic Arts/`. When the
prefix was made by another wine (e.g. Wine Staging, whose user is the macOS user
name), `install-client.sh` copies that user's `Electronic Arts` folder there,
unless `crossover` already has one.

## A killed client leaves the character linkdead for 60 s

When the client is killed instead of quitting with `/quit`, the server keeps the
character linkdead for 60 s. A login in that window is refused with "still being
logged out from linkdeath" and the client sits at the login, which looks like a
hang. The server logs `Linkdead player` when the connection drops and
`<account> just disconnected` once the character is gone. `client/tools/stop-client.sh`
waits for that line in the server log (only the bytes written after the kill) before
returning, and `launch-client.sh` counts a login as successful only on a new world
entry, not on the `LoginRequestHandler` line the server writes even for a refused
login.
