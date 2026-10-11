#!/bin/bash
# bench-run.sh — one controlled benchmark run of the DAoC client.
# Usage: bench-run.sh <duration-seconds> [outfile]
# Phases: ensure clean state → launch client (quick-login) → wait world entry →
#         settle 45 s → movement driver <duration> s (with 2 s sampler) → report CSV.
set -u
DUR="${1:-300}"
OUT="${2:-/Users/ada/development/games/daoc-macos/client/bench-results.csv}"
ROOT="/Users/ada/development/games/daoc-macos"
WINEBIN="$ROOT/dist/wine/Wine Staging.app/Contents/Resources/wine/bin"
WINELOG=/tmp/daoc-wine.log
SLOG="$ROOT/server/dist/daoc-server/logs/server.log"
export WINEPREFIX="$ROOT/dist/prefix"
SI="$ROOT/client/input-helper/sendinput.exe"

# 0. clean state: no client, no wineserver. A killed client leaves the player
# linkdead for 60 s — wait for a FRESH "just disconnected" line (bytes written
# after the kill) before relaunching, or the next login hangs.
KILL_LOG_POS=$(wc -c < "$SLOG" 2>/dev/null | tr -d ' '); KILL_LOG_POS=${KILL_LOG_POS:-0}
pkill -f "Z:.*game.dll" 2>/dev/null; sleep 2
"$WINEBIN/wineserver" -k 2>/dev/null; sleep 3
for i in $(seq 1 15); do
    if tail -c "+$((KILL_LOG_POS + 1))" "$SLOG" 2>/dev/null | grep -q "macadmin just disconnected"; then
        echo "disconnect confirmed (waited ~$((i*5))s)"; break
    fi
    sleep 5
done
# Hold display + system awake for the whole run (App Nap / display sleep guard).
caffeinate -dimsu -w $$ 2>/dev/null &
CAFFEINATE_PID=$!

# 1. launch client (quick-login args: ip port realm account pass char realm#)
# Credentials come from the login keychain — never hardcoded in this repo.
ACCT=$(security find-generic-password -s daoc-offline -a login_account -w 2>/dev/null)
PW=$(security find-generic-password -s daoc-offline -a login_password -w 2>/dev/null)
if [ -z "$ACCT" ] || [ -z "$PW" ]; then echo "FAIL: credentials not in keychain"; exit 1; fi
: > "$WINELOG"
open -n "$ROOT/dist/DAoCLauncher.app" --env WINEDEBUG=trace+frametime --env DAOC_LAUNCHER_RETRIES=1 --args wine game.dll 127.0.0.1 20300 42 "$ACCT" "$PW" Ada 3

# 2. wait for world entry with hang retries. Protocol per attempt: the launcher
# starts ONE client (RETRIES=1 so the launcher's own loop can't double-start);
# poll every 3 s for up to 150 s for world entry OR a crash exit. A crash is
# visible as the client process vanishing. Only a full 150 s of nothing counts
# as a hang. Up to 4 attempts total.
ATTEMPT=0
while true; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -gt 4 ]; then echo "FAIL: no world entry in 4 attempts"; exit 1; fi
    echo "launch attempt $ATTEMPT/4"
    BASE_W=$(grep -c "entering Region" "$SLOG" 2>/dev/null || echo 0)
    GOT_WORLD=0
    for i in $(seq 1 50); do
        sleep 3
        NOW_W=$(grep -c "entering Region" "$SLOG" 2>/dev/null || echo 0)
        NOW_C=$(pgrep -f "Z:.*game.dll" | wc -l | tr -d ' ')
        if [ "$NOW_W" -gt "$BASE_W" ]; then echo "world entry after ~$((i*3))s (attempt $ATTEMPT)"; GOT_WORLD=1; break; fi
        if [ "$NOW_C" -eq 0 ]; then echo "client died before login (t=$((i*3))s)"; break; fi
    done
    [ "$GOT_WORLD" -eq 1 ] && break
    # client died or hung — clean up fully (linkdead wait uses bytes-after-kill)
    KILL_LOG_POS2=$(wc -c < "$SLOG" 2>/dev/null | tr -d ' '); KILL_LOG_POS2=${KILL_LOG_POS2:-0}
    pkill -f "Z:.*game.dll" 2>/dev/null; sleep 2
    "$WINEBIN/wineserver" -k 2>/dev/null; sleep 3
    for j in $(seq 1 15); do
        if tail -c "+$((KILL_LOG_POS2 + 1))" "$SLOG" 2>/dev/null | grep -q "macadmin just disconnected"; then
            echo "disconnect confirmed (waited ~$((j*5))s)"; break
        fi
        sleep 5
    done
    : > "$WINELOG"
    open -n "$ROOT/dist/DAoCLauncher.app" --env WINEDEBUG=trace+frametime --env DAOC_LAUNCHER_RETRIES=1 --args wine game.dll 127.0.0.1 20300 42 "$ACCT" "$PW" Ada 3
    sleep 5
done

# 3. settle 45 s (let streaming textures/objects load)
sleep 45

# 4. movement driver with 2 s sampler in background writing (unixtime, count)
SAMPLER="$OUT.sampler"
( while true; do echo "$(date +%s) $(grep -c 'Frame duration' "$WINELOG" 2>/dev/null)"; sleep 2; done > "$SAMPLER" ) &
SAMPLER_PID=$!
"$ROOT/client/bench-drive.sh" "$DUR" 2>/dev/null
kill $SAMPLER_PID 2>/dev/null; kill $CAFFEINATE_PID 2>/dev/null
echo "bench complete: sampler=$SAMPLER winelog=$WINELOG"
