#!/bin/zsh
# launch-client.sh — credential-safe client launcher with hang watchdog.
# Reads creds from the login keychain at runtime (never written to disk),
# aborts if missing, opens the DAoC launcher, then watches: if no world entry has
# appeared and the wine log has been static for 60 s while the game process
# sits under 1% CPU (or 240 s pass without a login), the client is hung —
# kill the whole tree and relaunch (up to $1 times, default 3).
RETRIES="${1:-3}"
ROOT="${0:A:h:h:h}"   # repo root (this file is client/tools/launch-client.sh)
LOG=/tmp/daoc-wine.log
SLOG="$ROOT/server/dist/daoc-server/logs/server.log"
# Success = a new world entry. A LoginRequestHandler line alone is not enough:
# the server logs it even when it refuses the login ("still being logged out
# from linkdeath").
WORLD_ENTRIES_BEFORE=$(grep -c "WorldInitRequestHandler" "$SLOG" 2>/dev/null || echo 0)

launch_once () {
  ACCT=$(/usr/bin/security find-generic-password -s daoc-offline -a login_account -w 2>/dev/null)
  PW=$(/usr/bin/security find-generic-password -s daoc-offline -a login_password -w 2>/dev/null)
  if [ -z "$ACCT" ] || [ -z "$PW" ]; then
    echo "ABORT: keychain credentials unavailable (unlock the login keychain in a GUI session)" >&2
    return 2
  fi
  cd "$ROOT" || return 2
  # LaunchServices drops the caller's environment, so wine/x87sidecar/Metal
  # HUD knobs must ride on --env. Forward them only when set: an empty
  # ROSETTA_X87_PATH would disable the sidecar instead of selecting the
  # bundled one.
  local -a extra_env
  local v
  for v in DAOC_WINE_HOME DAOC_WINEPREFIX WINE_COMPATDB ROSETTA_X87_PATH DAOC_FTLOG_DIR DAOC_FPS_OVERLAY \
           ${(k)parameters[(I)X87_*]} ${(k)parameters[(I)MTL_*]}; do
    [ -n "${(P)v+set}" ] && extra_env+=(--env "$v=${(P)v}")
  done
  open -n dist/DAoCLauncher.app \
    --env "WINEDEBUG=${DAOC_WINEDEBUG:-trace+frametime}" \
    --env "DAOC_LAUNCHER_RETRIES=8" \
    "${extra_env[@]}" \
    --args wine game.dll 127.0.0.1 20300 42 "$ACCT" "$PW" "${DAOC_CHARACTER:-Ada}" "${DAOC_REALM:-3}"
}

# Kill the app launcher's own relaunch loop first (or it respawns wine in the
# gap), then every wine/game process for this prefix, and wait for wineserver
# to exit, so a relaunch never overlaps a previous client.
kill_tree () {
  local prefix="${DAOC_WINEPREFIX:-$ROOT/dist/prefix}"
  local wine_home="${DAOC_WINE_HOME:-$ROOT/dist/wine}"
  pkill -f "DAoCLauncher.app/Contents/MacOS/launch" 2>/dev/null
  WINEPREFIX="$prefix" "$wine_home/bin/wineserver" -k 2>/dev/null || true
  pkill -9 -f "game.dll" 2>/dev/null
  pkill -9 -f x87sidecar 2>/dev/null
  WINEPREFIX="$prefix" "$wine_home/bin/wineserver" -w 2>/dev/null || true
}

# Cumulative CPU time (centiseconds) of the game process, from /usr/bin/top:
# ps misreports both %cpu and cputime for Rosetta-translated wine processes
# (~2% / a few seconds for a thread pegged at 100% for minutes).
game_cputime_cs () {
  local pid t cs=0
  for pid in $(ps -Ao pid=,command= | awk '/game\.dll/ && !/awk|MacOS\/launch|start\.exe/ {print $1}'); do
    t=$(/usr/bin/top -l 1 -pid "$pid" -stats time | tail -1)
    cs=$((cs + $(echo "$t" | awk '{ n = split($1, a, ":"); s = a[n] + (n > 1 ? a[n-1] * 60 : 0) + (n > 2 ? a[n-2] * 3600 : 0); printf "%d", s * 100 }')))
  done
  echo "$cs"
}

try=0
while [ "$try" -lt "$RETRIES" ]; do
  try=$((try+1))
  launch_once || exit 2
  # Watch up to 240 s for the client to log in; detect hangs by log growth + CPU.
  waited=0; last_size=$(wc -c < "$LOG" 2>/dev/null || echo 0); stall=0; last_cs=$(game_cputime_cs)
  while [ "$waited" -lt 240 ]; do
    sleep 10; waited=$((waited+10))
    entries=$(grep -c "WorldInitRequestHandler" "$SLOG" 2>/dev/null || echo 0)
    [ "$entries" -gt "$WORLD_ENTRIES_BEFORE" ] && { echo "IN_WORLD after ${waited}s"; exit 0; }
    size=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    if [ "$size" -eq "$last_size" ]; then stall=$((stall+10)); else stall=0; last_size=$size; fi
    cs=$(game_cputime_cs); busy=$((cs - last_cs)); last_cs=$cs
    # Hung = log static 60 s AND the game burned <0.5 s CPU in the last 10 s.
    if [ "$stall" -ge 60 ] && [ "$busy" -lt 50 ]; then
      echo "HUNG: wine log static ${stall}s, game cpu ${busy}cs/10s, not in world — killing tree (try $try/$RETRIES)"
      break
    fi
  done
  [ "$waited" -ge 240 ] && echo "TIMEOUT: not in world after 240s (try $try/$RETRIES) — killing tree"
  kill_tree
done
echo "GAVE_UP after $try tries" >&2
exit 1
