#!/usr/bin/env bash
# graphics.sh - optional graphical patches for the installed client, from the
# pinned OfflineDAoC-macOS-graphics project (manifest.json "graphics").
#
#   ./graphics.sh                         -> checklist: pick the patches to turn on
#   ./graphics.sh status | list
#   ./graphics.sh enable <patch>... [--archives <part>...]   (patches: retina, srgb, textures)
#   ./graphics.sh disable <patch>...
#   ./graphics.sh textures inspect|install|use|uninstall|recover|status ...
#
# Nothing here runs unless you call it: install-client.sh never pulls the
# graphics project. The first call clones the pinned commit into
# upstream/graphics/ and verifies it; every call then runs that checkout's
# daoc-gfx against this install's client (dist/OfflineDAoC), wine (dist/wine)
# and prefix (dist/prefix). DAOC_WINE_HOME and DAOC_WINEPREFIX override the
# last two, as they do for the launcher. Each patch, and what turning it off
# restores, is in the graphics project's README.
set -euo pipefail
cd "$(dirname "$0")" && cd "$(pwd -P)"

manifest_pin() { python3 -c "import json; print(json.load(open('manifest.json'))['$1']['$2'])"; }

REPO=$(manifest_pin graphics repo)
REF=$(manifest_pin graphics ref)
SRC_DIR="upstream/graphics"
APP_DIR="dist/OfflineDAoC/runtime/client-opendaoc/app"
WINE_HOME="${DAOC_WINE_HOME:-dist/wine}"
PREFIX="${DAOC_WINEPREFIX:-dist/prefix}"

[[ -f $APP_DIR/game.dll ]] || { echo "graphics: no client in $APP_DIR — run ./install-client.sh first" >&2; exit 1; }

mkdir -p upstream
if [[ ! -d $SRC_DIR/.git ]]; then
  echo "== graphics: cloning ${REPO##*/} at ${REF:0:12}" >&2
  git clone --quiet "$REPO" "$SRC_DIR"
fi
if [[ $(git -C "$SRC_DIR" rev-parse HEAD) != "$REF" ]]; then
  echo "== graphics: checking out pinned ${REF:0:12}" >&2
  git -C "$SRC_DIR" fetch --quiet origin "$REF" 2>/dev/null || git -C "$SRC_DIR" fetch --quiet origin
  git -C "$SRC_DIR" checkout --quiet --detach "$REF"
fi
actual=$(git -C "$SRC_DIR" rev-parse HEAD)
[[ $actual == "$REF" ]] || { echo "graphics: $SRC_DIR is at ${actual:0:12}, pinned ${REF:0:12}" >&2; exit 1; }

(( $# )) || set -- select
exec python3 "$SRC_DIR/daoc-gfx" --app "$APP_DIR" --wine "$WINE_HOME" --prefix "$PREFIX" "$@"
