#!/bin/zsh
# kill-client.sh — tear down this install's DAoC client tree and wait for its
# wineserver to exit, so a relaunch never overlaps a previous client. Scoped
# to this install: other installs' launchers, clients and sidecars are never
# signalled. Follows the launcher's DAOC_WINE_HOME / DAOC_WINEPREFIX overrides.
ROOT="${0:A:h:h:h}"   # repo root (this file is client/tools/kill-client.sh)
WINE_HOME="${${DAOC_WINE_HOME:-$ROOT/dist/wine}:A}"   # resolved: lsof reports real paths
PREFIX="${DAOC_WINEPREFIX:-$ROOT/dist/prefix}"

# The app launcher's relaunch loop first, or it respawns wine in the gap. It
# is a bash script, so this install's bundle path is in its argv.
/usr/bin/pkill -f "$ROOT/dist/DAoCLauncher.app/Contents/MacOS/launch" 2>/dev/null
WINEPREFIX="$PREFIX" "$WINE_HOME/bin/wineserver" -k 2>/dev/null
# Stragglers wineserver -k missed: game.dll and x87sidecar processes with
# files mapped from this install's wine (CrossOver wine shows only
# "game.dll <args>" as argv, and macOS does not expose other processes'
# environments; same test as e2e-test.sh client_pids).
for pid in $(/usr/bin/pgrep -f 'game\.dll|x87sidecar' 2>/dev/null); do
  /usr/sbin/lsof -a -p "$pid" -Fn 2>/dev/null | grep -qF "n$WINE_HOME/" && kill -9 "$pid" 2>/dev/null
done
WINEPREFIX="$PREFIX" "$WINE_HOME/bin/wineserver" -w 2>/dev/null
exit 0
