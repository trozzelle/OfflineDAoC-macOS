#!/bin/bash
# build-app.sh [OUT_DIR] - assemble OfflineDAoC.app (unsigned) in OUT_DIR (default app/dist).
#
# Contents/MacOS/OfflineDAoC     the SwiftUI shell (swift build -c release)
# Contents/Resources/python/     python-build-standalone (app/python.lock), trimmed
# Contents/Resources/daoc/       the code root: daoc, daoc_cli/, manifest.json, version.txt,
#                                client/DAoCLauncher.app, server/tools/setup-dotnet.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo="$(cd "$here/.." && pwd -P)"
out="${1:-$here/dist}"
version="$(cat "$repo/version.txt")"
# shellcheck source=python.lock
. "$here/python.lock"

swift build -c release --arch arm64 --package-path "$here"
bin="$(swift build -c release --arch arm64 --package-path "$here" --show-bin-path)"

app="$out/OfflineDAoC.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin/OfflineDAoC" "$app/Contents/MacOS/OfflineDAoC"
sed "s/@VERSION@/$version/g" "$here/Info.plist" > "$app/Contents/Info.plist"

code="$app/Contents/Resources/daoc"
mkdir -p "$code/client" "$code/server/tools"
cp "$repo/daoc" "$repo/manifest.json" "$repo/version.txt" "$code/"
rsync -a --exclude __pycache__ "$repo/daoc_cli" "$code/"
cp -R "$repo/client/DAoCLauncher.app" "$code/client/"
cp "$repo/server/tools/setup-dotnet.sh" "$code/server/tools/"

cache="$here/.cache"
mkdir -p "$cache"
tarball="$cache/$(basename "${PYTHON_URL//%2B/+}")"
if [[ ! -f $tarball ]]; then
  curl -fsSL "$PYTHON_URL" -o "$tarball.tmp"
  echo "$PYTHON_SHA256  $tarball.tmp" | shasum -a 256 -c - >/dev/null
  mv "$tarball.tmp" "$tarball"
fi
echo "$PYTHON_SHA256  $tarball" | shasum -a 256 -c - >/dev/null
python="$app/Contents/Resources/python"
mkdir -p "$python"
tar -xzf "$tarball" -C "$python" --strip-components 1
# Nothing daoc_cli imports: tests, IDLE, Tk and its Tcl extensions, pip, build configuration.
rm -rf "$python"/lib/python3.*/test "$python"/lib/python3.*/idlelib "$python"/lib/python3.*/tkinter \
  "$python"/lib/python3.*/ensurepip "$python"/lib/python3.*/lib-dynload/_tkinter* \
  "$python"/lib/python3.*/config-3.*-darwin \
  "$python"/lib/libtcl* "$python"/lib/libtk* "$python"/lib/tcl* "$python"/lib/tk* \
  "$python"/lib/itcl* "$python"/lib/thread* "$python"/lib/tdbc* \
  "$python"/bin/idle3* "$python"/bin/pip*

# The tarball ships almost no compiled stdlib, and Python would write the missing .pyc
# files into the bundle on first import, after signing. Compile them now, with hashes that
# are never checked against the sources, so the signed bundle never changes (the launcher
# also runs the bundled Python with -B).
libs=("$python"/lib/python3.*)
[[ ${#libs[@]} -eq 1 && -d ${libs[0]} ]] || { echo "build-app: expected one $python/lib/python3.* directory" >&2; exit 1; }
"$python/bin/python3" -I -m compileall -q -f -j0 --invalidation-mode unchecked-hash "${libs[0]}" "$code/daoc_cli"

# Smoke: the bundled launcher runs on the bundled Python.
smoke="$(mktemp -d)"
DAOC_DATA="$smoke" "$code/daoc" --version
rm -rf "$smoke"
echo "$app"
