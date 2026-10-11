#!/usr/bin/env bash
# build-release.sh - build the portable macOS server folder and zip.
#
#   tools/build-release.sh            -> dist/daoc-server/ and dist/daoc-server-<version>-macos-arm64.zip
#
# Needs the .NET 10 SDK, cmake, clang (Xcode Command Line Tools) and curl. The result needs none
# of them: it bundles the .NET runtime and contains a fresh Classic + SI world built from the
# pinned upstream OpenDAoC-Database plus world/patches.
# Navmeshes come from world/navmesh (installed into dist/daoc-server); no client files are included.
#
# macOS port of the Linux repo's tools/build-release.sh. Differences from Linux:
#   - RID is osx-arm64 (Apple Silicon; the Linux repo targets linux-x64).
#   - The native pathing library builds as libDetour.dylib and ships as bin/lib/Detour.dylib.
#     .NET probes "lib/Detour" as "lib/Detour.dylib" on macOS, matching the Linux behaviour where
#     it probes lib/Detour.so.
#   - The release archive is a zip (macOS ships unzip; tar.gz would also work, but the Linux
#     tarball convention stays in the Linux repo).
#   - Codesigning: the bundled .NET runtime and the Detour library are ad-hoc signed at build
#     time so Gatekeeper quarantine and hardened-runtime checks do not block execution.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"                           # this repo (macOS port)
# The Linux source repo this port is built from: the pinned upstream clone install-server.sh
# makes in upstream/server (read-only reference; see vendor/README.md).
REPO="${DAOC_SOURCE_REPO:-$(cd "$HERE/.." && pwd)/upstream/server}"
# Where the vendored System.Data.SQLite source lives (see vendor/README.md).
SDS_SRC="${SDS_SRC:-$HERE/vendor/System.Data.SQLite}"
SDS_PROJ="$SDS_SRC/System.Data.SQLite.NetStandard21.csproj"
DOTNET="${DOTNET:-${DOTNET_ROOT:-$HOME/.dotnet}/dotnet}"
[[ -x $DOTNET ]] || DOTNET="${DOTNET:-$(command -v dotnet || true)}"
VERSION="${VERSION:-$(git -C "$HERE" describe --tags --always 2>/dev/null || echo dev)}"
OUT="$HERE/dist/daoc-server"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1

missing=()
"$DOTNET" --list-sdks 2>/dev/null | grep -q '^10\.' || missing+=(".NET 10 SDK (install: curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0)")
command -v cmake >/dev/null || missing+=("cmake (brew install cmake)")
command -v clang++ >/dev/null || missing+=("clang (Xcode Command Line Tools: xcode-select --install)")
command -v curl >/dev/null || missing+=("curl")
if ((${#missing[@]})); then
  echo "build-release: missing: ${missing[*]}" >&2
  echo "  See README.md for setup instructions." >&2
  exit 1
fi

# Build from a snapshot of the reference repo's source so the macOS patches in patches/ can be
# applied without touching the reference checkout. Only source projects are copied (no build
# outputs); SNAPSHOT is reused between runs (rsync-style refresh) to keep rebuilds fast.
SNAPSHOT="$HERE/build/src"
mkdir -p "$SNAPSHOT"
echo "== Syncing source snapshot from $REPO/src"
rsync -a --delete \
  --exclude='.git' \
  --exclude='Release/' --exclude='build/' --exclude='bin/' --exclude='obj/' \
  "$REPO/src/" "$SNAPSHOT/"
# The WorldBuilder needs a config dir for its serverconfig (the build only needs it to exist).
[[ -f $SNAPSHOT/CoreServer/config/serverconfig.xml ]] ||
  cp "$SNAPSHOT/CoreServer/config/serverconfig.example.xml" "$SNAPSHOT/CoreServer/config/serverconfig.xml"
for p in "$HERE"/patches/*.patch; do
  [[ -e $p ]] || break
  echo "== Applying $(basename "$p")"
  patch -p1 -d "$SNAPSHOT/.." -i "$p" --forward >/dev/null || { echo "build-release: patch failed: $p" >&2; exit 1; }
done

# Never replace bin/ under a live server.
if [[ -x $OUT/daoc-server.sh ]] && DAOC_HOME="$OUT" "$OUT/daoc-server.sh" status | grep -q '^running'; then
  echo "build-release: the server in $OUT is running; stop it first (./daoc-server.sh stop)" >&2
  exit 1
fi
# The folder is also the user's install: replace only what the build owns. config/, data/
# (accounts, characters, bots), logs/ and run/ are the user's and survive every rebuild;
# navmesh/ is refreshed in place by the navmesh step below.
rm -rf "$OUT/bin" "$OUT/defaults" "$OUT/daoc-server.sh" "$OUT/daoc-admin" "$OUT/daoc-progress" "$OUT/navmesh-install.sh" \
  "$OUT/release.conf" "$OUT/README.md" "$OUT/README-MACOS.md" "$OUT/VERSION"
echo "== Publishing server (self-contained osx-arm64)"
"$DOTNET" publish "$SNAPSHOT/CoreServer/CoreServer.csproj" -c Release -r osx-arm64 --self-contained true \
  -o "$OUT/bin" -nologo -v quiet -clp:ErrorsOnly

# daoc-admin shares bin/ (and its bundled runtime) with the server.
echo "== Publishing daoc-admin (TUI + CLI)"
"$DOTNET" publish "$SNAPSHOT/DaocAdmin/DaocAdmin.csproj" -c Release -r osx-arm64 --self-contained true \
  -o "$OUT/bin" -nologo -v quiet -clp:ErrorsOnly

# daoc-progress (port addition: upstream's progress importer for world upgrades) shares bin/ too.
# It references the vendored System.Data.SQLite project directly, so it never binds SQLite.Interop.
echo "== Publishing daoc-progress (world upgrade / progress import)"
"$DOTNET" publish "$HERE/tools/ProgressImport/ProgressImport.csproj" -c Release -r osx-arm64 --self-contained true \
  -o "$OUT/bin" -nologo -v quiet -clp:ErrorsOnly

echo "== Building native pathing library"
cmake -S "$SNAPSHOT/Pathing/Detour" -B "$HERE/build/detour" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 >/dev/null
cmake --build "$HERE/build/detour" >/dev/null
mkdir -p "$OUT/bin/lib"
# LibraryImport("lib/Detour") probes lib/Detour.dylib on macOS (lib/Detour.so on Linux).
cp -L "$HERE/build/detour/libDetour.dylib" "$OUT/bin/lib/Detour.dylib"
# Ad-hoc signature: the shared library was built by a different toolchain than the .NET runtime;
# keep every Mach-O in the folder validly signed so execution is never blocked.
codesign --force --sign - "$OUT/bin/lib/Detour.dylib" >/dev/null 2>&1 || true

# A post-build step copies translations into src/Release/ only; publish needs them too.
# (BSD install has no -D; rsync preserves the relative layout instead.)
mkdir -p "$OUT/bin/languages"
rsync -a --include='*/' --include='*.txt' --exclude='*' "$SNAPSHOT/GameServer/language/" "$OUT/bin/languages/" >/dev/null 2>&1 || \
  (cd "$SNAPSHOT/GameServer/language" && find . -type d -exec mkdir -p "$OUT/bin/languages/{}" \; && find . -name '*.txt' -exec cp {} "$OUT/bin/languages/{}" \;)

# System.Data.SQLite 1.0.119 ships prebuilt native SQLite.Interop binaries for win-x86/x64,
# linux-x64 and osx-x64 only — there is no osx-arm64 build, and its interop exports hashed
# symbol names. The project source (same version) compiled with SQLITE_STANDARD binds the
# plain system libsqlite3 ("sqlite3") with plain entry names, which macOS ships. Build the
# managed assembly from the vendored source and use it instead of the NuGet package's copy.
echo "== Building System.Data.SQLite (SQLITE_STANDARD: uses the macOS system libsqlite3)"
if [[ ! -f $SDS_PROJ ]]; then
  echo "build-release: missing $SDS_PROJ — see vendor/README.md for how to vendor it" >&2
  exit 1
fi
"$DOTNET" build "$SDS_PROJ" -c Release -p:UseInteropDll=false -p:UseSqliteStandard=true \
  -p:SignAssembly=false -p:PublicSign=false -p:DelaySign=false -nologo -v quiet -clp:ErrorsOnly
sds_dll="$SDS_SRC/obj/Release/netstandard2.1/System.Data.SQLite.dll"
[[ -f $sds_dll ]] || { echo "build-release: System.Data.SQLite build produced no output" >&2; exit 1; }
# Overlay it onto every output that carries the NuGet stub's interop-variant dll: the server
# publish output and the WorldBuilder build output (WorldBuilder links CoreDatabase too, and
# it must bind the system libsqlite3 the same way when it builds the world database).
echo "== Building the world (upstream OpenDAoC-Database + world/patches)"
dump=$("$HERE/tools/fetch-upstream-db.sh")
"$DOTNET" build "$SNAPSHOT/WorldBuilder/WorldBuilder.csproj" -c Release -nologo -v quiet -clp:ErrorsOnly
# Overlay it onto every output that carries the NuGet stub's interop-variant dll: the server
# publish output and the WorldBuilder build output (WorldBuilder links CoreDatabase too and
# must bind the system libsqlite3 the same way). This runs AFTER the WorldBuilder build so
# the restore process cannot put the stub's variant back.
for out_dir in "$OUT/bin" "$SNAPSHOT/WorldBuilder/bin/Release/net10.0"; do
  [[ -d $out_dir ]] || continue
  cp "$sds_dll" "$out_dir/System.Data.SQLite.dll"
  # The stub's native runtimes are not needed (and osx-arm64 does not exist); drop them so
  # nothing probes SQLite.Interop.dll.
  rm -rf "$out_dir/runtimes"
done
mkdir -p "$OUT/defaults"
"$DOTNET" "$SNAPSHOT/WorldBuilder/bin/Release/net10.0/DaocWorldBuilder.dll" \
  --source "$dump" --out "$OUT/defaults/world.sqlite" --patches "$REPO/world/patches" | grep -E "^(Schema|World)"

# The server reads config/ next to its program and navmesh/ from its working directory (bin/).
rm -rf "$OUT/bin/config"
ln -s ../config "$OUT/bin/config"
ln -s ../navmesh "$OUT/bin/navmesh"
ln -s ../logs "$OUT/bin/logs"

cp "$REPO/deploy/serverconfig.template.xml" "$OUT/defaults/serverconfig.xml"
cp "$SNAPSHOT/GameServer/config/logconfig.xml" "$SNAPSHOT/GameServer/config/invalidnames.txt" "$OUT/defaults/"
cp "$HERE/deploy/daoc-server.sh" "$HERE/deploy/daoc-admin" "$HERE/deploy/daoc-progress" "$HERE/deploy/navmesh-install.sh" \
  "$REPO/deploy/release.conf" "$OUT/"
cp "$REPO/deploy/README-release.md" "$OUT/README.md"
cp "$HERE/README.md" "$OUT/README-MACOS.md"
echo "$VERSION" > "$OUT/VERSION"

# Ad-hoc-sign every Mach-O the dotnet publish step laid down; quarantine/hardened-runtime checks
# then behave like on Linux (nothing to approve, nothing to bypass).
echo "== Ad-hoc codesigning"
find "$OUT/bin" -type f \( -perm -111 -o -name '*.dylib' \) -print0 | while IFS= read -r -d '' f; do
  file "$f" | grep -q Mach-O && codesign --force --sign - "$f" >/dev/null 2>&1 || true
done

# Navmeshes ship in the source as ~90 MB parts (world/navmesh/; under GitHub's 100 MB file limit).
# Join and verify them, and install them into the folder so dist/daoc-server is ready to start.
echo "== Navmeshes (world/navmesh)"
navset="daoc-navmeshes-classic-si-2.tar.xz"
nav="$HERE/dist/$navset"
want=$(<"$REPO/world/navmesh/$navset.sha256")
if [[ ! -f $nav || $(shasum -a 256 "$nav" | cut -d' ' -f1) != "$want" ]]; then
  cat "$REPO/world/navmesh/$navset".part-* > "$nav.tmp"
  [[ $(shasum -a 256 "$nav.tmp" | cut -d' ' -f1) == "$want" ]] || { echo "build-release: navmesh parts in world/navmesh are damaged" >&2; exit 1; }
  mv "$nav.tmp" "$nav"
fi
cp "$REPO/world/navmesh/$navset.sha256" "$nav.sha256"
DAOC_HOME="$OUT" "$OUT/navmesh-install.sh" --from-archive "$nav"

# The release zip leaves the navmeshes out (they are the separate archive above).
zipfile="$HERE/dist/daoc-server-$VERSION-macos-arm64.zip"
rm -f "$zipfile"
# User state (config/, data/, logs/, run/) never goes into the release zip.
(cd "$HERE/dist" && zip -rq "$zipfile" daoc-server -x "daoc-server/navmesh/*" \
  -x "daoc-server/config/*" -x "daoc-server/data/*" -x "daoc-server/logs/*" -x "daoc-server/run/*")
echo "== Done: $OUT"
echo "         $zipfile ($(du -h "$zipfile" | cut -f1))"