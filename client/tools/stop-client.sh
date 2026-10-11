#!/bin/zsh
# stop-client.sh — stop this install's DAoC client tree (kill-client.sh), then
# wait until the server has dropped the linkdead character (60 s after a kill),
# so the next login is not refused with "still being logged out from
# linkdeath".
ROOT="${0:A:h:h:h}"
SLOG="$ROOT/server/dist/daoc-server/logs/server.log"
before=$(wc -c < "$SLOG" 2>/dev/null || echo 0)
"$ROOT/client/tools/kill-client.sh"
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
