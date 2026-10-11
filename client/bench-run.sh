#!/bin/zsh
# bench-run.sh — the client performance gate.
#   bench-run.sh [seconds=300] [tag=bench]      (run from a GUI Terminal: Keychain)
#
# Starts from a stopped client, logs the benchmark character in (launch-client.sh,
# credentials from the login Keychain), settles 45 s, then plays for <seconds>:
# NPC interaction + movement through a town (bench-drive.sh). Frame times come
# from the present probe (client/tools/frametime: one timestamp per presented
# Metal frame) over exactly the play window.
#
# PASS = average FPS >= 60 and p95 frame time <= 16.7 ms (<= 17.0 ms when the
# renderer reports vsync on). 1%-low FPS is reported, not gated. The run is
# invalid (exit 2) if the probe saw no frames, the renderer state is unknown,
# or the character did not move away from the last NPC it interacted with.
#
# The bench needs GM rights for /jump and /target on NPCs: it raises the account
# to gm for the run and restores the previous role afterwards.
# Requires: a running server (server/dist/daoc-server), mingw-w64 (input helper),
# Xcode command line tools (probe), sqlite3.
set -u
DUR=${1:-300}; TAG=${2:-bench}
ROOT="${0:A:h:h}"
SRV="$ROOT/server/dist/daoc-server"
DB="$SRV/data/opendaoc.sqlite3.db"
ACCOUNT="${DAOC_BENCH_ACCOUNT:-$(/usr/bin/security find-generic-password -s daoc-offline -a login_account -w 2>/dev/null)}"
CHAR="${DAOC_CHARACTER:-Ada}"
OUT="${DAOC_BENCH_OUT:-/tmp/daoc-bench-$TAG}"
admin() { DAOC_ADMIN_SOCKET="$SRV/run/admin.sock" "$SRV/bin/DaocAdmin" "$@"; }
pos() { sqlite3 "$DB" "SELECT Xpos, Ypos FROM DOLCharacters WHERE Name='$CHAR'"; }
invalid() { echo "INVALID: $*"; exit 2; }

make -s -C "$ROOT/client/input-helper" sendinput.exe || invalid "cannot build the input helper (brew install mingw-w64)"
make -s -C "$ROOT/client/tools/frametime" || invalid "cannot build the frametime probe"
admin status >/dev/null 2>&1 || invalid "server not running ($SRV)"
rm -rf "$OUT"; mkdir -p "$OUT/ftlog"

"$ROOT/client/tools/stop-client.sh"
role=$(admin accounts show "$ACCOUNT" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["role"])')
[ "$role" = player ] && admin accounts set-role "$ACCOUNT" gm >/dev/null
restore() { [ "$role" = player ] && admin accounts set-role "$ACCOUNT" player >/dev/null; }
trap restore EXIT
# zsh skips the EXIT trap when a signal kills it: restore on those as well.
trap 'restore; exit 130' INT TERM HUP

export DAOC_FTLOG_DIR="$OUT/ftlog"
"$ROOT/client/tools/launch-client.sh" 3 || invalid "client never entered the world"
sleep 45
F=$(ls -S "$OUT"/ftlog/ftlog-*.txt 2>/dev/null | head -1)   # the game's presenter writes the most
[ -n "$F" ] || invalid "frametime probe wrote nothing (was ftlog.dylib injected?)"
l0=$(wc -l < "$F"); sleep 2; [ "$(wc -l < "$F")" -gt "$l0" ] || invalid "probe file is not growing: $F"
gpid=${${F:t:r}#ftlog-}
MLOG=$(ls -t "$ROOT"/dist/OfflineDAoC/runtime/client-opendaoc/app/mtld3d-logs/game-"$gpid".log 2>/dev/null | head -1)
VSYNC=$(grep -aoE "\(vsync (on|off), maxFps [0-9]+\)" "$MLOG" 2>/dev/null | tail -1)
[ -n "$VSYNC" ] || invalid "renderer vsync/frame-cap state not found (mtld3d log for pid $gpid)"

l0=$(wc -l < "$F"); t0=$(date +%s)
DAOC_BENCH_STATE="$OUT/last-npc" "$ROOT/client/bench-drive.sh" "$DUR"
t1=$(date +%s); sleep 1; l1=$(wc -l < "$F")
sed -n "$((l0 + 1)),${l1}p" "$F" > "$OUT/window.ns"
# A server that died mid-run leaves the client rendering a disconnected world.
admin status >/dev/null 2>&1 || invalid "server stopped during the play window"

"$ROOT/client/tools/stop-client.sh"    # logout saves the character's position
read -r x y <<< "$(pos | tr '|' ' ')"
npc=$(cat "$OUT/last-npc" 2>/dev/null)
npos=$(sqlite3 "$DB" "SELECT X, Y FROM Mob WHERE Name='$npc' LIMIT 1" | tr '|' ' ')
read -r nx ny <<< "$npos"
moved=$(python3 -c "import math; print(int(math.hypot($x-${nx:-0}, $y-${ny:-0})))")

python3 - "$OUT/window.ns" "$TAG" "$VSYNC" "$t0" "$t1" "$npc" "$moved" <<'EOF'
import sys
path, tag, vsync, t0, t1, npc, moved = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6], int(sys.argv[7])
ts = [int(l) for l in open(path) if l.strip()]
ft = [(b - a) / 1e6 for a, b in zip(ts, ts[1:])]           # ms
if len(ft) < 100: print(f"INVALID: only {len(ft)} frames in the window"); sys.exit(2)
span = (ts[-1] - ts[0]) / 1e9
s = sorted(ft); n = len(ft)
pct = lambda q: s[min(n - 1, int(q * n))]
low1 = s[int(0.99 * n):]
avg_fps = n / span
p95 = pct(0.95)
limit = 17.0 if "vsync on" in vsync else 16.7
print(f"[{tag}] renderer {vsync}; play window {t1 - t0}s, {n} frames over {span:.1f}s")
print(f"  avg FPS {avg_fps:.1f} | frame time mean {sum(ft)/n:.2f} ms, p50 {pct(.5):.2f}, p95 {p95:.2f}, p99 {pct(.99):.2f}, max {s[-1]:.1f}")
print(f"  1%-low FPS {1000 / (sum(low1) / len(low1)):.1f} (diagnostic) | frames > 50 ms: {sum(1 for x in ft if x > 50)}")
print(f"  movement: ended {moved} units from the last NPC interacted with ({npc})")
if moved < 300: print("INVALID: the character did not move away from the NPC"); sys.exit(2)
ok = avg_fps >= 60 and p95 <= limit
print(f"GATE: {'PASS' if ok else 'FAIL'} (avg >= 60 FPS, p95 <= {limit} ms)")
sys.exit(0 if ok else 1)
EOF
