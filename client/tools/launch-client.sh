#!/bin/zsh
# launch-client.sh — credential-safe client launcher with hang watchdog.
# Reads creds from the login keychain at runtime (never written to disk),
# aborts if missing, opens the DAoC launcher, then watches: if no world entry has
# appeared and the wine log has been static for 60 s while the game process
# sits under 1% CPU (or 240 s pass without a login), the client is hung —
# kill the whole tree and relaunch (up to $1 times, default 3).
# The client enters the world as $DAOC_CHARACTER, else the account's most
# recently played character (read from the server's database), in that
# character's realm.
#   launch-client.sh --credentials   ask for and save the game account if none is saved
#   launch-client.sh --character     print the character a launch would use
RETRIES="${1:-3}"
ROOT="${0:A:h:h:h}"   # repo root (this file is client/tools/launch-client.sh)
LOG=/tmp/daoc-wine.log
SLOG="$ROOT/server/dist/daoc-server/logs/server.log"
DB="$ROOT/server/dist/daoc-server/data/opendaoc.sqlite3.db"
# Game port: $DAOC_PORT, else <Port> from the server's config (as daoc-server.sh reads it), else 10300.
SRVCONF="$ROOT/server/dist/daoc-server/config/serverconfig.xml"
PORT="${DAOC_PORT:-$(sed -n 's:.*<Port>\([0-9]*\)</Port>.*:\1:p' "$SRVCONF" 2>/dev/null | head -1)}"
PORT="${PORT:-10300}"
# Success = a new world entry. A LoginRequestHandler line alone is not enough:
# the server logs it even when it refuses the login ("still being logged out
# from linkdeath").
# grep -c prints 0 *and* exits 1 when nothing matches: never chain `|| echo 0`.
world_entries () { local n; n=$(grep -c "WorldInitRequestHandler" "$SLOG" 2>/dev/null); echo "${n:-0}"; }
WORLD_ENTRIES_BEFORE=$(world_entries)

# Game account from the login Keychain; on first run, ask once and store it.
load_credentials () {
  ACCT=$(/usr/bin/security find-generic-password -s daoc-offline -a login_account -w 2>/dev/null)
  PW=$(/usr/bin/security find-generic-password -s daoc-offline -a login_password -w 2>/dev/null)
  [ -n "$ACCT" ] && [ -n "$PW" ] && return 0
  [ -t 0 ] || { echo "ABORT: no saved game account; run client/tools/launch-client.sh in Terminal once" >&2; return 2; }
  read -r "ACCT?Game account name: "
  /usr/bin/security add-generic-password -U -s daoc-offline -a login_account -w "$ACCT" || return 2
  # Bare -w last: security prompts for the password itself (no echo, not on argv).
  echo "Game account password:" >&2
  /usr/bin/security add-generic-password -U -s daoc-offline -a login_password -w || return 2
  PW=$(/usr/bin/security find-generic-password -s daoc-offline -a login_password -w 2>/dev/null)
  [ -n "$PW" ] || { echo "ABORT: game account password not saved" >&2; return 2; }
}

# Sets CHAR_NAME and CHAR_REALM (1 Albion, 2 Midgard, 3 Hibernia) for $ACCT.
load_character () {
  local row
  row=$(python3 - "$DB" "$ACCT" "${DAOC_CHARACTER:-}" <<'EOF'
import pathlib, sqlite3, sys
db, acct, name = sys.argv[1:]
try:
    con = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True)
    q = "SELECT Name, Realm FROM DOLCharacters WHERE AccountName = ? COLLATE NOCASE"
    if name:
        row = con.execute(q + " AND Name = ?", (acct, name)).fetchone()
    else:
        row = con.execute(q + " ORDER BY LastPlayed DESC, AccountSlot LIMIT 1", (acct,)).fetchone()
except sqlite3.Error as e:
    sys.exit(f"ABORT: cannot read characters from {db}: {e}")
if not row:
    sys.exit(f"ABORT: account {acct} has no character {name}" if name else
             f"ABORT: account {acct} has no character; create one in the client first")
print(*row)
EOF
  ) || return 2
  read -r CHAR_NAME CHAR_REALM <<< "$row"
}
[ "${1:-}" = --credentials ] && { load_credentials; exit $?; }
[ "${1:-}" = --character ] && { load_credentials && load_character && print -r -- "$CHAR_NAME"; exit $?; }

launch_once () {
  load_credentials && load_character || return 2
  cd "$ROOT" || return 2
  # LaunchServices drops the caller's environment, so wine/x87sidecar/Metal
  # HUD knobs must ride on --env. Forward them only when set: an empty
  # ROSETTA_X87_PATH would disable the sidecar instead of selecting the
  # bundled one.
  local -a extra_env
  local v
  for v in DAOC_WINE_HOME DAOC_WINEPREFIX DAOC_DLL_OVERRIDES WINE_COMPATDB ROSETTA_X87_PATH DAOC_FTLOG_DIR DAOC_FPS_OVERLAY \
           ${(k)parameters[(I)X87_*]} ${(k)parameters[(I)MTL_*]}; do
    [ -n "${(P)v+set}" ] && extra_env+=(--env "$v=${(P)v}")
  done
  open -n dist/DAoCLauncher.app \
    --env "WINEDEBUG=${DAOC_WINEDEBUG:-trace+frametime}" \
    --env "DAOC_LAUNCHER_RETRIES=8" \
    "${extra_env[@]}" \
    --args wine game.dll 127.0.0.1 "$PORT" 42 "$ACCT" "$PW" "$CHAR_NAME" "$CHAR_REALM"
}

# Cumulative CPU time (centiseconds) of the game process. Absolute /bin/ps:
# some shells shadow ps with a builtin that misreports translated processes.
game_cputime_cs () {
  /bin/ps -Ao time=,args= | awk '/game\.dll/ && !/awk|MacOS\/launch|start\.exe/ {
      n = split($1, a, ":"); s = a[n] + (n > 1 ? a[n-1] * 60 : 0) + (n > 2 ? a[n-2] * 3600 : 0); cs += s * 100 }
    END { printf "%d", cs + 0 }'
}

try=0
while [ "$try" -lt "$RETRIES" ]; do
  try=$((try+1))
  launch_once || exit 2
  # Watch up to 240 s for the client to log in; detect hangs by log growth + CPU.
  waited=0; last_size=$(wc -c < "$LOG" 2>/dev/null || echo 0); stall=0; last_cs=$(game_cputime_cs)
  while [ "$waited" -lt 240 ]; do
    sleep 10; waited=$((waited+10))
    entries=$(world_entries)
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
  "$ROOT/client/tools/kill-client.sh"   # launcher loop + this prefix's wine tree
done
echo "GAVE_UP after $try tries" >&2
exit 1
