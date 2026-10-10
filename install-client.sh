#!/usr/bin/env bash
# install-client.sh - set up the OfflineDAoC client under Wine on macOS.
#
#   ./install-client.sh              -> dist/OfflineDAoC/  (patched client)
#                                       dist/wine/Wine Staging.app
#                                       dist/prefix/         (wine prefix)
#                                       client/DAoCLauncher.app (session wrapper)
#
# Steps:
#   1. Verify requirements (macOS, Rosetta 2, python3, GStreamer framework).
#   2. Fetch + verify the Gcenx Wine Staging tarball (SHA-256 from manifest.json).
#   3. Fetch + verify the pinned OfflineDAoC release parts (per-part + whole-archive
#      SHA-256, same scheme as upstream's Get-OfflineDAoC.ps1), join, extract.
#   4. Apply the client encryption-bypass patch to game.dll (byte-verified).
#   5. Initialize the wine prefix (win10 mode) and install the launcher wrapper.
#
# Everything is cached in downloads/ (gitignored); re-runs skip finished steps.
set -euo pipefail
cd "$(dirname "$0")" && cd "$(pwd -P)"   # repo root (client/ lives here); resolve symlinks

manifest_pin() { python3 -c "import json; print(json.load(open('manifest.json'))['$1']['$2'])"; }

WINE_URL=$(manifest_pin wine url)
WINE_TARBALL=$(manifest_pin wine tarball)
WINE_SHA=$(manifest_pin wine sha256)
REL_URL=$(manifest_pin client release_url)
REL_VER=$(manifest_pin client version)
ROOT_FOLDER=$(manifest_pin client root_folder)
ARCHIVE_SHA=$(manifest_pin client archive_sha256)

DIST="dist"
WINE_APP="$DIST/wine/Wine Staging.app"
CLIENT_ROOT="$DIST/OfflineDAoC"
APP_DIR="$CLIENT_ROOT/runtime/client-opendaoc/app"
PREFIX="$DIST/prefix"
LAUNCHER_SRC="client/DAoCLauncher.app"
LAUNCHER_DST="$DIST/DAoCLauncher.app"

echo "== install-client: OfflineDAoC v$REL_VER + Wine Staging"

# --- 1. Requirements -------------------------------------------------------
[[ $(uname -s) == "Darwin" ]] || { echo "install-client: macOS required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "install-client: python3 required" >&2; exit 1; }
if [[ $(uname -m) == "arm64" ]]; then
  # The Wine build is x86_64; Apple Silicon needs Rosetta 2 (oahd is its daemon).
  /usr/bin/pgrep -q oahd 2>/dev/null || {
    echo "install-client: Rosetta 2 not installed (softwareupdate --install-rosetta --agree-to-license)" >&2
    exit 1
  }
fi
# Wine runs without the GStreamer framework, but audio/video in games typically
# needs it. The prior verification used this machine without GStreamer installed,
# so treat it as optional with a warning rather than a hard requirement.
if [[ $(uname -m) == "arm64" ]] && [[ ! -d "/Library/Frameworks/GStreamer.framework" ]]; then
  echo "install-client: NOTE — GStreamer.framework is not installed."
  echo "  Wine works without it, but in-game audio may be silent."
  echo "  Free install: https://gstreamer.freedesktop.org/download/ (macOS runtime installer)"
fi
command -v curl >/dev/null || { echo "install-client: curl required" >&2; exit 1; }

mkdir -p downloads "$DIST"

# --- 2. Wine ---------------------------------------------------------------
if [[ ! -d $WINE_APP ]]; then
  if [[ ! -f "downloads/$WINE_TARBALL" ]]; then
    echo "== downloading Wine ($WINE_TARBALL)"
    curl -fsSL --retry 3 "$WINE_URL" -o "downloads/$WINE_TARBALL"
  fi
  actual=$(shasum -a 256 "downloads/$WINE_TARBALL" | cut -d' ' -f1)
  [[ $actual == "$WINE_SHA" ]] || {
    echo "install-client: wine tarball checksum mismatch" >&2
    echo "  expected $WINE_SHA" >&2; echo "  actual   $actual" >&2; exit 1;
  }
  echo "== extracting Wine"
  mkdir -p "$DIST/wine"
  tar -xJf "downloads/$WINE_TARBALL" -C "$DIST/wine"
  # Ad-hoc sign everything: Gatekeeper quarantine must not block the bundle.
  find "$WINE_APP" -type f -print0 | xargs -0 -I{} sh -c \
    'file "$1" | grep -q Mach-O && xattr -d com.apple.quarantine "$1" 2>/dev/null || true' _ {} 2>/dev/null || true
else
  echo "== wine already installed"
fi

# --- 3. OfflineDAoC release ------------------------------------------------
if [[ ! -d $CLIENT_ROOT ]]; then
  echo "== fetching OfflineDAoC v$REL_VER (this is a ~5 GB download)"
  python3 client/fetch_release.py "$REL_URL" "downloads/v$REL_VER" "$ROOT_FOLDER" "$DIST"
  # fetch_release.py extracts to $DIST/<RootFolder>; normalize the name.
  [[ -d "$DIST/$ROOT_FOLDER" ]] && mv "$DIST/$ROOT_FOLDER" "$CLIENT_ROOT"
else
  echo "== OfflineDAoC already installed"
fi

# --- 4. Client patch -------------------------------------------------------
if [[ -f "$APP_DIR/game.dll.orig" ]]; then
  echo "== client already patched"
else
  echo "== applying the client encryption-bypass patch"
  python3 client/apply_game_patch.py "$APP_DIR/game.dll"
fi

# --- 5. Wine prefix + launcher --------------------------------------------
if [[ ! -f $PREFIX/system.reg ]]; then
  echo "== initializing wine prefix (win10)"
  WINE="$WINE_APP/Contents/Resources/wine/bin/wine"
  export WINEPREFIX="$PWD/$PREFIX"   # absolute: wine rejects relative WINEPREFIX
  "$WINE" wineboot -i >/dev/null 2>&1
  "$WINE" winecfg -v win10 >/dev/null 2>&1
  # Wait for wineserver to flush the registry hives before checking them.
  "$WINE_APP/Contents/Resources/wine/bin/wineserver" -w
  [[ -f $PREFIX/system.reg ]] || { echo "install-client: prefix init failed" >&2; exit 1; }
else
  echo "== wine prefix already initialized"
fi

# The launcher wrapper resolves paths relative to its bundle location.
rm -rf "$LAUNCHER_DST"
cp -R "$LAUNCHER_SRC" "$LAUNCHER_DST"
xattr -dr com.apple.quarantine "$LAUNCHER_DST" 2>/dev/null || true

echo "== install-client: done"
echo "   launch the game (server running):"
echo "     open -n $DIST/DAoCLauncher.app --args wine game.dll 127.0.0.1 10300 42 <account> <password>"