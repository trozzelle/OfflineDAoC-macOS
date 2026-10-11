#!/bin/zsh
# stop-client.sh — stop the DAoC client tree, then wait until the server has
# dropped the linkdead character (60 s after a kill), so the next login is not
# refused with "still being logged out from linkdeath". Follows the launcher's
# DAOC_WINE_HOME / DAOC_WINEPREFIX overrides.
ROOT="${0:A:h:h:h}"
SLOG="$ROOT/server/dist/daoc-server/logs/server.log"
WINE_HOME="${DAOC_WINE_HOME:-$ROOT/dist/wine}"
PREFIX="${DAOC_WINEPREFIX:-$ROOT/dist/prefix}"
before=$(wc -c < "$SLOG" 2>/dev/null || echo 0)
pkill -f "DAoCLauncher.app/Contents/MacOS/launch" 2>/dev/null
WINEPREFIX="$PREFIX" "$WINE_HOME/bin/wineserver" -k 2>/dev/null
pkill -9 -f "game\.dll" 2>/dev/null
pkill -9 -f x87sidecar 2>/dev/null
WINEPREFIX="$PREFIX" "$WINE_HOME/bin/wineserver" -w 2>/dev/null
echo "$(date +%T) client stopped"
sleep 3
if tail -c +$((before + 1)) "$SLOG" 2>/dev/null | grep -q "Linkdead player"; then
  for i in {1..45}; do
    tail -c +$((before + 1)) "$SLOG" | grep -q " just disconnected" && { echo "$(date +%T) server dropped the character"; break; }
    sleep 2
  done
fi
# Anything wine-related still alive is a leak (e.g. another prefix's wineserver).
/bin/ps -Ao pid=,comm= | awk '$2 ~ /wine|x87sidecar|preloader/ {print "leftover:", $1, $2}'
