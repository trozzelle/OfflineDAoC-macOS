#!/usr/bin/env bash
# install-client.sh - set up the OfflineDAoC client under Wine on macOS.
#
#   ./install-client.sh              -> dist/OfflineDAoC/  (patched client)
#                                       dist/wine/           (CrossOver Wine + x87sidecar)
#                                       dist/prefix/         (wine prefix)
#                                       client/DAoCLauncher.app (session wrapper)
#
# Steps:
#   1. Verify requirements (macOS, Rosetta 2, python3).
#   2. Fetch + verify athei/wine-build (SHA-256 from manifest.json): CrossOver Wine
#      with the x87sidecar Rosetta x87 JIT and mtld3d (D3D9 on Metal).
#   3. Fetch + verify the pinned OfflineDAoC release parts (per-part + whole-archive
#      SHA-256, same scheme as upstream's Get-OfflineDAoC.ps1), join, extract.
#   4. Apply the client encryption-bypass patch to game.dll (byte-verified).
#   5. Initialize the wine prefix (win10 version setting, profile folders kept
#      inside the prefix) and install the launcher wrapper.
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
WINE_HOME="$DIST/wine"
CLIENT_ROOT="$DIST/OfflineDAoC"
APP_DIR="$CLIENT_ROOT/runtime/client-opendaoc/app"
PREFIX="$DIST/prefix"
LAUNCHER_SRC="client/DAoCLauncher.app"
LAUNCHER_DST="$DIST/DAoCLauncher.app"

echo "== install-client: OfflineDAoC v$REL_VER + CrossOver Wine (x87sidecar)"

# --- 1. Requirements -------------------------------------------------------
[[ $(uname -s) == "Darwin" ]] || { echo "install-client: macOS required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "install-client: python3 required" >&2; exit 1; }
if [[ $(uname -m) == "arm64" ]]; then
  # The Wine build is x86_64; Apple Silicon needs Rosetta 2. A functional probe
  # (can we execute an x86_64 binary?) beats checking for the oahd daemon, whose
  # process name varies across macOS versions.
  if ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
    echo "install-client: Rosetta 2 not installed (softwareupdate --install-rosetta --agree-to-license)" >&2
    exit 1
  fi
fi
# The wine bundle carries its own libraries (no GStreamer needed): audio goes
# through winecoreaudio.
command -v curl >/dev/null || { echo "install-client: curl required" >&2; exit 1; }

mkdir -p downloads "$DIST"

# --- 2. Wine ---------------------------------------------------------------
if [[ ! -x $WINE_HOME/bin/wine ]]; then
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
  rm -rf "$WINE_HOME"
  tar -xJf "downloads/$WINE_TARBALL" -C "$DIST"   # the tarball's root is wine/
  # Gatekeeper quarantine must not block the bundle's binaries.
  xattr -dr com.apple.quarantine "$WINE_HOME" 2>/dev/null || true
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
  python3 client/apply_game_patch.py "$APP_DIR/game.dll" "$PWD/manifest.json"
fi

# --- 5. Wine prefix + launcher --------------------------------------------
if [[ ! -f $PREFIX/system.reg ]]; then
  echo "== initializing wine prefix (win10 version)"
  WINE="$WINE_HOME/bin/wine"
  export WINEPREFIX="$PWD/$PREFIX"   # absolute: wine rejects relative WINEPREFIX
  "$WINE" wineboot -i >/dev/null 2>&1
  "$WINE" reg add "HKCU\\Software\\Wine" /v Version /d win10 /f >/dev/null 2>&1 || true
  # Wait for wineserver to flush the registry hives before checking them.
  "$WINE_HOME/bin/wineserver" -w
  [[ -f $PREFIX/system.reg ]] || { echo "install-client: prefix init failed" >&2; exit 1; }
else
  echo "== wine prefix already initialized"
fi
# Bring an existing prefix (e.g. one made by an older wine) up to this wine's
# version now, so its first game launch does not do it.
WINEPREFIX="$PWD/$PREFIX" "$WINE_HOME/bin/wine" wineboot -u >/dev/null 2>&1
WINEPREFIX="$PWD/$PREFIX" "$WINE_HOME/bin/wineserver" -w
# Wine links the Windows profile folders (Documents, Desktop, ...) of every
# prefix user (this wine's is "crossover") to the macOS home folders. The first
# touch of ~/Documents raises a TCC prompt for the wine binary and the client
# blocks until it is answered, so keep those folders inside the prefix.
find "$PREFIX/drive_c/users" -maxdepth 3 -type l | while IFS= read -r link; do
  rm "$link" && mkdir -p "$link"
done

# The launcher wrapper resolves paths relative to its bundle location.
rm -rf "$LAUNCHER_DST"
cp -R "$LAUNCHER_SRC" "$LAUNCHER_DST"
xattr -dr com.apple.quarantine "$LAUNCHER_DST" 2>/dev/null || true

echo "== install-client: done"
echo "   launch the game (server running):"
echo "     open -n $DIST/DAoCLauncher.app --args wine game.dll 127.0.0.1 10300 42 <account> <password>"