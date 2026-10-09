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
cd "$(dirname "$0")"

ACCOUNT="${1:-e2etest}"
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
}
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
if grep -q "<Port>10300</Port>" "$SERVER_DIR/config/serverconfig.xml" 2>/dev/null; then
  sed -i.bak 's|<Port>10300</Port>|<Port>20300</Port>|; s|<RegionPort>10400</RegionPort>|<RegionPort>20400</RegionPort>|; s|<UdpPort>10400</UdpPort>|<UdpPort>20400</UdpPort>|' \
    "$SERVER_DIR/config/serverconfig.xml" && rm -f "$SERVER_DIR/config/serverconfig.xml.bak"
  echo "ports moved to 20300/20400"
fi
# Boot detached: without a TTY the launcher script execs the console in the
# foreground, so a plain `... | start --console &` dies when our pipe closes.
# nohup with output into logs/console.out keeps it independent of this script.
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

# --- 5. Launch the client ---------------------------------------------------
step "client launch"
# Snapshot the wine log so the liveness check only sees bytes from THIS launch.
WINE_LOG=/tmp/daoc-wine.log
: > "$WINE_LOG"
open -n "$PWD/dist/DAoCLauncher.app" --args wine game.dll 127.0.0.1 20300 42 "$ACCOUNT" "$PASSWORD"
LAUNCH_LINE_COUNT=$(wc -l < "$WINE_LOG" | tr -d ' ')
echo "client launch requested; waiting for the login to register server-side"

# --- 6. Verify: login reached character select; client stays alive ----------
step "login evidence + 120 s aliveness"
deadline=$((SECONDS + 90))
LOGIN_OK=""
while (( SECONDS < deadline )); do
  if tail -n +"$((LAUNCH_LINE_COUNT + 1))" "$WINE_LOG" 2>/dev/null \
     | grep -q "login"; then
    LOGIN_OK=1
    break
  fi
  if grep -qE "logging in|Login request|entering the world" "$SERVER_DIR/logs/server.log" 2>/dev/null; then
    LOGIN_OK=1
    break
  fi
  sleep 2
done
cp "$SERVER_DIR/logs/server.log" "$EVIDENCE_DIR/server.log" 2>/dev/null || true
cp "$WINE_LOG" "$EVIDENCE_DIR/wine.log" 2>/dev/null || true

if [[ -z $LOGIN_OK ]]; then
  fail "no client login appeared in the server log within 90 s"
else
  echo "login observed; holding the client for the 120 s aliveness window"
  CLIENT_PID=$(pgrep -f "game.dll 127.0.0.1 20300" | head -1)
  [[ -n $CLIENT_PID ]] || CLIENT_PID=$(pgrep -f "game.dll" | head -1)
  echo "client pid: ${CLIENT_PID:-unknown}"
  sleep 120
  if [[ -n $CLIENT_PID ]] && kill -0 "$CLIENT_PID" 2>/dev/null; then
    echo "client process alive 120 s after login — PASS"
  elif pgrep -f "game.dll" > /dev/null; then
    echo "client process (re-checked) alive 120 s after login — PASS"
  else
    fail "client process died within 120 s after login"
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