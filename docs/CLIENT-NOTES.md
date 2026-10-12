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
and the prompt is easy to miss behind other windows. `daoc client install` replaces
those symlinks with real directories inside the prefix, so the prompt never
appears. Runs with the Metal Performance HUD (`DAOC_FPS_OVERLAY=1`) have still
raised a Documents prompt once with the prefix set up this way.

## The prefix's Windows user is `crossover` (rosetta) or you (arm64)

The CrossOver wine names its Windows user `crossover`, not the macOS user name.
The client's settings live in
`dist/prefix/drive_c/users/crossover/AppData/Roaming/Electronic Arts/`. When the
prefix was made by another wine (e.g. Wine Staging, whose user is the macOS user
name), `daoc client install` copies that user's `Electronic Arts` folder there,
unless `crossover` already has one. The arm64 Wine is upstream Wine, whose user is
the macOS user name; its prefix (`dist/prefix-arm64`) gets the folder from the
rosetta prefix the same way.

## game.dll's `Shared` section stops an arm64 Wine

game.dll has a 4-byte section named `Shared` flagged `IMAGE_SCN_MEM_SHARED`
(characteristics `0xd0000040`) at `0x247a000`, 4 KB-aligned. Wine maps a shared
section as a shared file mapping, which needs host-page alignment; an arm64 Wine
runs on 16 KB pages, logs `map_file_into_view unaligned shared mapping ... not
supported` and refuses the image: `wine: failed to start ... c000007b`,
"Bad EXE format". The Client patch clears the flag (`0xc0000040`); then the 4 bytes
are private to each client process instead of shared between simultaneous ones.
The rosetta Wine (x86_64, 4 KB pages) runs the patched game.dll the same as
before (login 8 s, 125 FPS at character select).

## The arm64 Wine waits 35 s per start until Local Network access is allowed

On each new Wine session `wineboot --init` resolves the Mac's own name
(`getaddrinfo("<name>.local")` in ws2_32.so). For Hadron's Wine that lookup sat
in `mdns_addrinfo` for ~35 s and failed ("Failed to resolve your host name IP")
while macOS held a Local Network permission prompt for it; the same lookup from
a native process returned at once. Allowing it cut a cold `wine cmd` from 36–45 s
to 3 s and the client's login from 46 s to 10 s. The prompt is easy to miss; the
setting is "wine" under System Settings > Privacy & Security > Local Network.
`daoc client install --wine arm64` checks for the warning after setting the
prefix up and says so.

## A killed client leaves the character linkdead for 60 s

When the client is killed instead of quitting with `/quit`, the server keeps the
character linkdead for 60 s. A login in that window is refused with "still being
logged out from linkdeath" and the client sits at the login, which looks like a
hang. The server logs `Linkdead player` when the connection drops and
`<account> just disconnected` once the character is gone. `daoc client stop`
waits for that line in the server log (only the bytes written after the kill) before
returning. `daoc client start` counts a login into the world as successful only
on a new world entry, not on the `LoginRequestHandler` line the server writes
even for a refused login. For an account with no character, which stops at
character select, it counts the `User <account> logging on!` line and treats a
`Wrong password` after it as a failure.

## Over SSH the login Keychain is locked

macOS unlocks the login keychain only for the session you logged in to. In an
SSH session `security find-generic-password … -w` fails with "User interaction is
not allowed" (exit 36) even while the GUI session has it unlocked. Item
attributes are still readable, so the account looks saved but its password can't
be read. `daoc client login`, `client start` and `client bench` run
`security unlock-keychain` on a terminal, and otherwise stop and say to run it
first. git's osxkeychain credential helper hits the same lock
(`failed to store: -25308` after a push over SSH); the push itself succeeds.
