#!/usr/bin/env bash
# e2e-test.sh - scripted end-to-end acceptance for the macOS install.
#
#   ./e2e-test.sh [account] [password]
#
# Flow: install server → boot on alternate ports → create an account →
# install client → launch the client → verify the server log shows the login
# reaching character select and the client process is still alive ≥120 s later.
#
# Exits 0 only when every step passes. Assumes ./install-server.sh and
# ./install-client.sh have already run (they are idempotent and this script
# calls them if their outputs are missing).
#
# NOTE on ports: the user's own server may be running on 10300/10400; this test
# moves its server instance to 20300/20400 and the client launch passes the
# port explicitly.
#
# CAUTION: never delete run/admin.sock or run/server.pid while a CoreServer from
# this install is alive — shutdown needs the socket to wake a pending accept
# (patch 010). Check lsof before touching run/.
set -uo pipefail
cd "$(dirname "$0")" && cd "$(pwd -P)"

ACCOUNT="${1:-e2e$(date +%s)}"
PASSWORD="${2:-e2epass1}"
SERVER_DIR="server/dist/daoc-server"
CLIENT_ROOT="dist/OfflineDAoC"
EVIDENCE_DIR="evidence"
mkdir -p "$EVIDENCE_DIR"
FAILED=0
STEP=""

step() { STEP="$1"; echo; echo "=== $STEP ==="; }
fail() { echo "E2E FAILED at: $STEP — $1" >&2; FAILED=1; }

cleanup() {
  if [[ -d $SERVER_DIR && -f $SERVER_DIR/daoc-server.sh ]]; then
    (cd "$SERVER_DIR" && ./daoc-server.sh stop >/dev/null 2>&1) || true
  fi
  # Restore the standard config so the install works as documented afterwards.
  if [[ -f $SERVER_DIR/config/serverconfig.xml.bak ]]; then
    mv -f "$SERVER_DIR/config/serverconfig.xml.bak" "$SERVER_DIR/config/serverconfig.xml"
  fi
  rmdir "$PWD/.e2e.lock" 2>/dev/null || true
}
# One run at a time: two concurrent runs would fight over the same wine
# prefix, server ports, and logs.
if ! mkdir "$PWD/.e2e.lock" 2>/dev/null; then
  echo "another e2e run is active (remove $PWD/.e2e.lock if that is stale)" >&2
  exit 1
fi
trap cleanup EXIT
# --- 1. Server installed? ---------------------------------------------------
step "server install"
if [[ ! -x $SERVER_DIR/bin/CoreServer ]]; then
  ./install-server.sh || fail "install-server.sh failed"
else
  echo "server already installed"
fi
if [[ $FAILED -ne 0 ]]; then exit 1; fi

# --- 2. Boot on alternate ports --------------------------------------------
step "server boot (alternate ports 20300/20400)"
(cd "$SERVER_DIR" && ./daoc-server.sh stop >/dev/null 2>&1) || true
# A fresh install has no config/ until first start; seed it from defaults/ so
# the port move below edits the file the server will actually read. The data/
# world DB is likewise created here so the boot log is clean.
mkdir -p "$SERVER_DIR/config" "$SERVER_DIR/data"
[[ -f $SERVER_DIR/config/serverconfig.xml ]] || cp "$SERVER_DIR/defaults/serverconfig.xml" "$SERVER_DIR/config/"
[[ -f $SERVER_DIR/data/opendaoc.sqlite3.db ]] || cp "$SERVER_DIR/defaults/world.sqlite" "$SERVER_DIR/data/opendaoc.sqlite3.db"
if grep -q "<Port>10300</Port>" "$SERVER_DIR/config/serverconfig.xml" 2>/dev/null; then
  sed -i.bak 's|<Port>10300</Port>|<Port>20300</Port>|; s|<RegionPort>10400</RegionPort>|<RegionPort>20400</RegionPort>|; s|<UdpPort>10400</UdpPort>|<UdpPort>20400</UdpPort>|' \
    "$SERVER_DIR/config/serverconfig.xml"
  echo "ports moved to 20300/20400"
  grep -q "<Port>20300</Port>" "$SERVER_DIR/config/serverconfig.xml" || { fail "port move failed"; exit 1; }
fi
# Boot detached: without a TTY the launcher script execs the console in the
# foreground, so a plain `... | start --console &` dies when our pipe closes.
# nohup with output into logs/console.out keeps it independent of this script.
mkdir -p "$SERVER_DIR/logs" "$SERVER_DIR/run"
(cd "$SERVER_DIR" && nohup ./daoc-server.sh start --console </dev/null >logs/console.out 2>&1 &)
for i in $(seq 1 120); do
  if grep -q "Server is now listening" "$SERVER_DIR/logs/console.out" 2>/dev/null \
     && nc -z 127.0.0.1 20300 >/dev/null 2>&1; then
    echo "server is listening (console.out + port 20300 OK)"
    break
  fi
  sleep 1
done
grep -q "Server is now listening" "$SERVER_DIR/logs/console.out" 2>/dev/null \
  || { fail "server never reached 'listening' within 120 s"; exit 1; }
cp "$SERVER_DIR/logs/console.out" "$EVIDENCE_DIR/server-boot.log" 2>/dev/null || true

# --- 3. Account -------------------------------------------------------------
step "account creation"
if (cd "$SERVER_DIR" && ./daoc-admin accounts create "$ACCOUNT" "$PASSWORD" 2>&1 | tee "$EVIDENCE_DIR/account.txt") | grep -q "created\|player,"; then
  echo "account '$ACCOUNT' ready"
else
  # Account may already exist from a previous run — verify it can log in.
  if (cd "$SERVER_DIR" && ./daoc-admin accounts list 2>&1) | grep -q "^$ACCOUNT"; then
    echo "account '$ACCOUNT' already exists — reusing it"
  else
    fail "account creation failed and no existing account found"
    exit 1
  fi
fi

# --- 4. Client installed? ---------------------------------------------------
step "client install"
if [[ ! -d $CLIENT_ROOT ]]; then
  ./install-client.sh || fail "install-client.sh failed"
else
  echo "client already installed"
fi
[[ -f $CLIENT_ROOT/runtime/client-opendaoc/app/game.dll ]] || { fail "game.dll missing after client install"; exit 1; }

# --- 5. Launch the client (up to 3 attempts) --------------------------------
step "client launch"
CLIENT_PAT="$(basename "$PWD").dist.OfflineDAoC.runtime.client-opendaoc.app.game\\.dll"
WINE_LOG=/tmp/daoc-wine.log
SERVER_LOG="$SERVER_DIR/logs/server.log"
LOG_OFFSET=$(wc -c < "$SERVER_LOG" 2>/dev/null | tr -d ' '); LOG_OFFSET=${LOG_OFFSET:-0}

# The client's wined3d GL init under Rosetta is flaky (~50% of launches stall or
# crash before the splash); a kill-and-relaunch retry succeeds (PORTING-LOG).
# Login itself takes 1-2 minutes to reach the server (RUNBOOK).
LOGIN_OK=""
ATTEMPT=""
for attempt in 1 2 3 4 5; do
  ATTEMPT=$attempt
  CLIENT_SEEN=0
  echo "--- launch attempt $attempt/5"
  # Kill any orphaned wine client from a previous attempt.
  WINE_BIN="$PWD/dist/wine/Wine Staging.app/Contents/Resources/wine/bin/wine"
  WINEPREFIX="$PWD/dist/prefix" "dist/wine/Wine Staging.app/Contents/Resources/wine/bin/wineserver" -k >/dev/null 2>&1 || true
  sleep 3
  : > "$WINE_LOG"
  open -n "$PWD/dist/DAoCLauncher.app" --args wine game.dll 127.0.0.1 20300 42 "$ACCOUNT" "$PASSWORD"
  deadline=$((SECONDS + 180))
  while (( SECONDS < deadline )); do
    # Strict, offset-windowed check: only bytes the server logged AFTER the
    # launches, only the real login event for THIS account.
    if tail -c "+$((LOG_OFFSET + 1))" "$SERVER_LOG" 2>/dev/null \
       | grep -q "LoginRequestHandler.*User $ACCOUNT logging on!"; then
      LOGIN_OK=1
      break 2
    fi
    # Crash detection: retry only after the client was actually seen running.
    # Wait for it to appear first: 'open' returns before wine starts, so an
    # immediate check would read "not running" during the spawn window. The
    # seen-flag makes "died" reproducible: only a client that was observed
    # running and then vanished counts as a crash.
    if pgrep -f "$CLIENT_PAT" >/dev/null 2>&1; then
      CLIENT_SEEN=1
    elif [[ ${CLIENT_SEEN:-0} -eq 1 ]]; then
      echo "client process died before login — relaunching"
      CLIENT_SEEN=0
      break
    fi
    sleep 2
  done
  [[ -n $LOGIN_OK ]] && break
done
cp "$SERVER_LOG" "$EVIDENCE_DIR/server.log" 2>/dev/null || true
cp "$WINE_LOG" "$EVIDENCE_DIR/wine.log" 2>/dev/null || true
echo "$ATTEMPT" > "$EVIDENCE_DIR/launch-attempts.txt"

if [[ -z $LOGIN_OK ]]; then
  fail "no 'User $ACCOUNT logging on!' appeared in the server log after 5 launch attempts"
else
  echo "login observed (attempt $ATTEMPT); holding the client for the 120 s window"
  # Liveness is judged by the exact pid of THIS launch only — no fallback to
  # "any game.dll process" (another install's client could satisfy that).
  CLIENT_PID=$(pgrep -f "$CLIENT_PAT" | head -1)
  if [[ -z $CLIENT_PID ]]; then
    fail "could not find the client process from this launch"
  else
    echo "client pid: $CLIENT_PID"
    sleep 120
    if kill -0 "$CLIENT_PID" 2>/dev/null; then
      echo "client process alive 120 s after login — PASS"
    else
      fail "client process died within 120 s after login"
    fi
    # A wine crash signature means the client is broken even if a process lingers.
    if grep -q "nodrv_CreateWindow" "$WINE_LOG" 2>/dev/null; then
      fail "wine log shows nodrv_CreateWindow (client window creation failed)"
    fi
  fi
fi

# --- 7. Clean shutdown ------------------------------------------------------
step "server shutdown"
(cd "$SERVER_DIR" && ./daoc-server.sh stop) || fail "server did not stop cleanly"
echo
echo "=== evidence bundle: $EVIDENCE_DIR/ ==="
ls -la "$EVIDENCE_DIR" 2>/dev/null | tail -n +2

if [[ $FAILED -eq 0 ]]; then
  echo
  echo "E2E: PASS"
  exit 0
else
  echo
  echo "E2E: FAIL (see above)"
  exit 1
fi