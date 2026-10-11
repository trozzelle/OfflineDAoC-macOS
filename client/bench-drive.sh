#!/bin/bash
# bench-drive.sh — scripted play for the DAoC benchmark: NPC interaction + movement.
# Usage: bench-drive.sh <duration-seconds>
#
# Each cycle teleports next to a townsfolk NPC (/jump, GM), targets it (/target,
# GM: NPCs within 800 units), faces it from a step away and right-clicks it,
# which is the game's interact action (a merchant opens its trade window), then
# closes the window and runs a forward/turn movement pattern through the town.
# The last thing each cycle does is walk, so the character always ends the run
# away from the NPC it last interacted with (bench-run.sh asserts that).
#
# DAOC_BENCH_NPCS overrides the NPC list (space-separated, unique names in the
# character's region). Default: the town in Connacht (Hibernia, region 200).
DUR="${1:-300}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SI="$ROOT/client/input-helper/sendinput.exe"
# Input must come from the game's own wineserver: follow the launcher's
# DAOC_WINE_HOME / DAOC_WINEPREFIX overrides.
WINE="${DAOC_WINE_HOME:-$ROOT/dist/wine}/bin/wine"
export WINEPREFIX="${DAOC_WINEPREFIX:-$ROOT/dist/prefix}"
read -r -a NPCS <<< "${DAOC_BENCH_NPCS:-Qunilan Aideen Freagus Llyn Eleri}"
STATE="${DAOC_BENCH_STATE:-/dev/null}"   # last jump target, for bench-run.sh

si() { "$WINE" "$SI" "$@" 2>/dev/null; }
# Release every key the pattern holds, so an aborted run never leaves the
# character running into a wall.
release() { for sc in 0x11 0x1F 0xE04B 0xE04D; do si sc "$sc" up; done; }
trap release EXIT

# Scan codes: W=0x11 fwd, S=0x1F back, LEFT=0xE04B, RIGHT=0xE04D (E0-extended:
# a bare 0x4B/0x4D is NUMPAD4/NUMPAD6)
END=$((SECONDS + DUR))
n=0
while (( SECONDS < END )); do
    npc=${NPCS[$((n % ${#NPCS[@]}))]}
    si chat "/jump to $npc"; sleep 2
    si chat "/target $npc"; sleep 1
    si chat "/face"; sleep 1
    si sc 0x1F down 900                      # step back so the NPC is in view
    si chat "/face"; sleep 1
    si rclick 0.50 0.47; sleep 0.5          # interact: the NPC's upper body,
    si rclick 0.50 0.53                      # lower for short races
    echo "$npc" > "$STATE"
    sleep 3
    si sc 0x01 down 50                       # Esc: close the NPC window
    si sc 0x1F down 600
    for step in "0xE04B 900" "0x11 6000" "0xE04D 1500" "0x11 5000" "0xE04B 2400" "0x11 6000"; do
        (( SECONDS < END )) || break
        si sc ${step% *} down ${step#* }
    done
    n=$((n + 1))
done
si sc 0x11 down 4000                         # always end walking away
echo "bench-drive: $n interaction cycles in ${DUR}s"
