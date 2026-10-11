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
# to gm for the run and restores the previous role afterwards. A marker file
# records the raise until the restore succeeds; if the server was gone at the
# end, the next run restores the account first (or run the printed command).
# Requires: a running server (server/dist/daoc-server), mingw-w64 (input helper),
# Xcode command line tools (probe), sqlite3.
set -u
DUR=${1:-300}; TAG=${2:-bench}
ROOT="${0:A:h:h}"
SRV="$ROOT/server/dist/daoc-server"
DB="$SRV/data/opendaoc.sqlite3.db"
# Asks for the game account once if none is saved; the bench character is the
# one launch-client.sh logs in with (DAOC_CHARACTER, else the most recently played).
CHAR=$("$ROOT/client/tools/launch-client.sh" --character) || exit 2
export DAOC_CHARACTER="$CHAR"
ACCOUNT="${DAOC_BENCH_ACCOUNT:-$(/usr/bin/security find-generic-password -s daoc-offline -a login_account -w 2>/dev/null)}"
OUT="${DAOC_BENCH_OUT:-$(mktemp -d -t "daoc-bench-$TAG")}" || exit 2
admin() { DAOC_ADMIN_SOCKET="$SRV/run/admin.sock" "$SRV/bin/DaocAdmin" "$@"; }
invalid() { echo "INVALID: $*"; exit 2; }
MARK="$SRV/run/bench-gm-raised"   # account raised to gm and not yet restored
setrole() { admin accounts set-role "$1" "$2" >/dev/null 2>&1; }

make -s -C "$ROOT/client/input-helper" sendinput.exe || invalid "cannot build the input helper (brew install mingw-w64)"
make -s -C "$ROOT/client/tools/frametime" || invalid "cannot build the frametime probe"
admin status >/dev/null 2>&1 || invalid "server not running ($SRV)"
if [ -f "$MARK" ]; then
    prev=$(<"$MARK")
    setrole "$prev" player || invalid "cannot restore $prev to player (left at gm by an earlier run)"
    rm -f "$MARK"; echo "restored $prev to player (left at gm by an earlier run)"
fi
rm -rf "$OUT/ftlog" "$OUT/last-npc" "$OUT/window.ns"; mkdir -p "$OUT/ftlog" || invalid "cannot create $OUT/ftlog"
echo "[$TAG] character $CHAR; output in $OUT"

"$ROOT/client/tools/stop-client.sh"
role=$(admin accounts show "$ACCOUNT" --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["role"])')
restore() {
    [ -f "$MARK" ] || return 0
    if setrole "$ACCOUNT" player; then rm -f "$MARK"; return 0; fi
    echo "WARNING: $ACCOUNT is still gm; the next bench-run.sh restores it, or run:" >&2
    echo "  DAOC_ADMIN_SOCKET='$SRV/run/admin.sock' '$SRV/bin/DaocAdmin' accounts set-role '$ACCOUNT' player" >&2
}
trap restore EXIT
# zsh skips the EXIT trap when a signal kills it: restore on those as well.
trap 'restore; exit 130' INT TERM HUP
if [ "$role" = player ]; then
    print -r -- "$ACCOUNT" > "$MARK"
    setrole "$ACCOUNT" gm || invalid "cannot raise $ACCOUNT to gm"
fi

export DAOC_FTLOG_DIR="$OUT/ftlog"
"$ROOT/client/tools/launch-client.sh" 3 || invalid "client never entered the world"
sleep 45
F=$(ls -S "$OUT"/ftlog/ftlog-*.txt 2>/dev/null | head -1)   # the game's presenter writes the most
[ -n "$F" ] || invalid "frametime probe wrote nothing (was ftlog.dylib injected?)"
l0=$(wc -l < "$F"); sleep 2; [ "$(wc -l < "$F")" -gt "$l0" ] || invalid "probe file is not growing: $F"
gpid=${${F:t:r}#ftlog-}
MLOG="$ROOT/dist/OfflineDAoC/runtime/client-opendaoc/app/mtld3d-logs/game-$gpid.log"
VSYNC=$(grep -aoE "\(vsync (on|off), maxFps [0-9]+\)" "$MLOG" 2>/dev/null | tail -1)
[ -n "$VSYNC" ] || invalid "renderer vsync/frame-cap state not found (mtld3d log for pid $gpid)"

l0=$(wc -l < "$F"); t0=$(date +%s)
DAOC_BENCH_STATE="$OUT/last-npc" "$ROOT/client/bench-drive.sh" "$DUR"
t1=$(date +%s); sleep 1; l1=$(wc -l < "$F")
sed -n "$((l0 + 1)),${l1}p" "$F" > "$OUT/window.ns"
# A server that died mid-run leaves the client rendering a disconnected world.
admin status >/dev/null 2>&1 || invalid "server stopped during the play window"

"$ROOT/client/tools/stop-client.sh"    # logout saves the character's position
npc=$(cat "$OUT/last-npc" 2>/dev/null)
[ -n "$npc" ] || invalid "bench-drive recorded no NPC interaction"
moved=$(python3 - "$DB" "$CHAR" "$npc" 2>&1 <<'EOF'
import math, pathlib, sqlite3, sys
db, char, npc = sys.argv[1:]
con = sqlite3.connect(pathlib.Path(db).as_uri() + "?mode=ro", uri=True)
row = con.execute("SELECT Region, Xpos, Ypos FROM DOLCharacters WHERE Name = ?", (char,)).fetchone()
if not row: sys.exit(f"character {char} not found in {db}")
region, x, y = row
mobs = con.execute("SELECT X, Y FROM Mob WHERE Name = ? AND Region = ?", (npc, region)).fetchall()
if len(mobs) != 1: sys.exit(f"NPC '{npc}' has {len(mobs)} Mob rows in region {region} (need exactly 1)")
print(int(math.hypot(x - mobs[0][0], y - mobs[0][1])))
EOF
) || invalid "$moved"

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
