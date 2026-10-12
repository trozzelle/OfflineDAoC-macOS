#!/usr/bin/env bash
# graphics.sh - optional graphical patches for the installed client, from the
# pinned OfflineDAoC-macOS-graphics project (manifest.json "graphics").
#
#   ./graphics.sh                         -> checklist: pick the patches to turn on
#   ./graphics.sh status | list
#   ./graphics.sh enable <patch>... [--archives <part>...]   (patches: retina, srgb, textures, anisotropy)
#   ./graphics.sh enable anisotropy --level 2|4|8|16       (also changes the level while it is on)
#   ./graphics.sh disable <patch>...
#   ./graphics.sh textures inspect|install|use|uninstall|recover|status ...
#
# Nothing here runs unless you call it: install-client.sh never pulls the
# graphics project. The first call clones the pinned commit into
# upstream/graphics/; every call checks that checkout is at the pin with no
# local changes (its d3d9.dll ends up loaded by the game), then runs its
# daoc-gfx against this install's client (dist/OfflineDAoC), wine (dist/wine)
# and prefix (dist/prefix). DAOC_WINE_HOME and DAOC_WINEPREFIX override the
# last two, as they do for the launcher. Each patch, and what turning it off
# restores, is in the graphics project's README.
set -euo pipefail
# No cd: relative --archives paths, the checklist's archive prompt and relative
# DAOC_WINE_HOME / DAOC_WINEPREFIX resolve against the caller's directory.
ROOT=$(cd "$(dirname "$0")" && pwd -P)

manifest_pin() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]][sys.argv[3]])' "$ROOT/manifest.json" "$1" "$2"; }

REPO=$(manifest_pin graphics repo)
REF=$(manifest_pin graphics ref)
SRC_DIR="$ROOT/upstream/graphics"
APP_DIR="$ROOT/dist/OfflineDAoC/runtime/client-opendaoc/app"
WINE_HOME="${DAOC_WINE_HOME:-$ROOT/dist/wine}"
PREFIX="${DAOC_WINEPREFIX:-$ROOT/dist/prefix}"

[[ -f $APP_DIR/game.dll ]] || { echo "graphics: no client in $APP_DIR — run ./install-client.sh first" >&2; exit 1; }

if [[ ! -d $SRC_DIR/.git ]]; then
  echo "== graphics: cloning ${REPO##*/} at ${REF:0:12}" >&2
  git clone --quiet "$REPO" "$SRC_DIR"
fi
# Refuse edited or untracked files: they would run (or, for d3d9.dll, be
# copied next to game.dll) as if they were the pinned commit.
if [[ -n $(git -C "$SRC_DIR" status --porcelain) ]]; then
  echo "graphics: $SRC_DIR has local changes (git -C \"$SRC_DIR\" status); remove that folder to re-clone the pinned commit" >&2
  exit 1
fi
if [[ $(git -C "$SRC_DIR" rev-parse HEAD) != "$REF" ]]; then
  echo "== graphics: checking out pinned ${REF:0:12}" >&2
  git -C "$SRC_DIR" fetch --quiet origin
  git -C "$SRC_DIR" checkout --quiet --detach "$REF"
fi
actual=$(git -C "$SRC_DIR" rev-parse HEAD)
[[ $actual == "$REF" ]] || { echo "graphics: $SRC_DIR is at ${actual:0:12}, pinned ${REF:0:12}" >&2; exit 1; }

(( $# )) || set -- select
exec python3 "$SRC_DIR/daoc-gfx" --app "$APP_DIR" --wine "$WINE_HOME" --prefix "$PREFIX" "$@"
