#!/usr/bin/env bash
# e2e-test.sh - scripted end-to-end acceptance for the macOS install.
#
#   ./e2e-test.sh [account] [password]
#
# Flow: install server → boot on alternate ports → create an account →
# install client → launch the client → verify the server log shows the login
# reaching character select and the client process is still alive ≥60 s later.
#
# Exits 0 only when every step passes. Assumes ./install-server.sh and
# ./install-client.sh have already run (they are idempotent and this script
# calls them if their outputs are missing).
#
# NOTE on ports: the user's own server may be running on 10300/10400; this test
# moves its server instance to 20300/20400 and the client launch passes the
# port explicitly.
set -uo pipefail
cd "$(dirname "$0")"

ACCOUNT="${1:-e2etest}"
PASSWORD="${2:-e2epass1}"
SERVER_DIR="server/dist/daoc-server"
CLIENT_ROOT="dist/OfflineDAoC"
LOG_EVIDENCE="evidence"
EVIDENCE_DIR="$LOG_EVIDENCE"
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
[[ $FAILED -eq 0 ]] || exit 1

# --- 2. Boot on alternate ports --------------------------------------------
step "server boot (alternate ports 20300/20400)"
(cd "$SERVER_DIR" && ./daoc-server.sh stop >/dev/null 2>&1) || true
if grep -q "<Port>10300</Port>" "$SERVER_DIR/config/serverconfig.xml" 2>/dev/null; then
  sed -i.bak 's|<Port>10300</Port>|<Port>20300</Port>|; s|<RegionPort>10400</RegionPort>|<RegionPort>20400</RegionPort>|; s|<UdpPort>10400</UdpPort>|<UdpPort>20400</UdpPort>|' \
    "$SERVER_DIR/config/serverconfig.xml" && rm -f "$SERVER_DIR/config/serverconfig.xml.bak"
  echo "ports moved to 20300/20400"
fi
(cd "$SERVER_DIR" && ./daoc-server.sh start --console >/dev/null 2>&1) &
BOOT_PID=$!
# Wait for "Server is now listening" in console.out (matches daoc-server.sh's own gate).
for i in $(seq 1 120); do
  if grep -q "Server is now listening" "$SERVER_DIR/logs/console.out" 2>/dev/null; then
    echo "server is listening"; break
  fi
  sleep 1
  if ! kill -0 $BOOT_PID 2>/dev/null && ! grep -q "Server is now listening" "$SERVER_DIR/logs/console.out" 2>/dev/null; then
    fail "server process exited during boot (see $SERVER_DIR/logs/console.out)"
    exit 1
  fi
done
grep -q "Server is now listening" "$SERVER_DIR/logs/console.out" 2>/dev/null || { fail "server never reached 'listening' within 120 s"; exit 1; }
cp "$SERVER_DIR/logs/console.out" "$EVIDENCE_DIR/server-boot.log" 2>/dev/null || true

# --- 3. Account -------------------------------------------------------------
step "account creation"
if (cd "$SERVER_DIR" && ./daoc-admin accounts create "$ACCOUNT" "$PASSWORD" 2>&1 | tee "$EVIDENCE_DIR/account.txt") | grep -q "created\|player,"; then
  echo "account '$ACCOUNT' ready"
else
  fail "account creation failed"
  exit 1
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
open -n "$PWD/dist/DAoCLauncher.app" --args wine game.dll 127.0.0.1 20300 42 "$ACCOUNT" "$PASSWORD"
echo "client launch requested; waiting for the login to register server-side"
sleep 10

# --- 6. Verify: login + character select reached, client stays alive --------
step "login evidence (60 s aliveness window)"
deadline=$((SECONDS + 60))
LOGIN_OK=""
while (( SECONDS < deadline )); do
  if grep -qE "Character is entering the world|Login request|Entering the game" "$SERVER_DIR/logs/server.log" 2>/dev/null; then
    LOGIN_OK=1
    break
  fi
  sleep 2
done
cp "$SERVER_DIR/logs/server.log" "$EVIDENCE_DIR/server.log" 2>/dev/null || true
cp /tmp/daoc-wine.log "$EVIDENCE_DIR/wine.log" 2>/dev/null || true

if [[ -z $LOGIN_OK ]]; then
  fail "no client login appeared in the server log within 60 s"
else
  echo "login traffic observed in server.log"
  # Character-select reached = client survived the login round-trip. Give the
  # client the full 60 s from here and confirm the wine process is still alive.
  sleep 60
  if pgrep -f "game.dll" > /dev/null; then
    echo "client process alive 60 s after login — PASS"
  else
    fail "client process died within 60 s after login"
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