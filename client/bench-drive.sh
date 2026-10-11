#!/bin/bash
# bench-drive.sh — scripted movement pattern for the DAoC client.
# Usage: bench-drive.sh <duration-seconds>
DUR="${1:-300}"
SI="/Users/ada/development/games/daoc-macos/client/input-helper/sendinput.exe"
# Input must come from the game's own wineserver: follow the launcher's
# DAOC_WINE_APP / DAOC_WINEPREFIX overrides.
WINE_APP="${DAOC_WINE_APP:-/Users/ada/development/games/daoc-macos/dist/wine/Wine Staging.app}"
WINE="$WINE_APP/Contents/Resources/wine/bin/wine"
export WINEPREFIX="${DAOC_WINEPREFIX:-/Users/ada/development/games/daoc-macos/dist/prefix}"
# unstick: back up 1.5s, sidestep, then start pattern
"$WINE" "$SI" sc 0x1F down 1500 2>/dev/null   # S back
"$WINE" "$SI" sc 0x4B down 900 2>/dev/null    # turn left
END=$((SECONDS + DUR))
# Scan codes: W=0x11 fwd, S=0x1F back, LEFT=0x4B, RIGHT=0x4D, A=0x1E, D=0x20
i=0
while (( SECONDS < END )); do
    case $((i % 8)) in
        0) "$WINE" "$SI" sc 0x11 down 7000 2>/dev/null ;;
        1) "$WINE" "$SI" sc 0x4B down 1200 2>/dev/null ;;
        2) "$WINE" "$SI" sc 0x11 down 7000 2>/dev/null ;;
        3) "$WINE" "$SI" sc 0x4D down 1200 2>/dev/null ;;
        4) "$WINE" "$SI" sc 0x11 down 5000 2>/dev/null ;;
        5) "$WINE" "$SI" sc 0x11 down 3000 2>/dev/null ;;
        6) "$WINE" "$SI" sc 0x4B down 2400 2>/dev/null ;;
        7) "$WINE" "$SI" sc 0x11 down 6000 2>/dev/null ;;
    esac
    i=$((i+1))
done
