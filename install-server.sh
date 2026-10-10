#!/usr/bin/env bash
# install-server.sh - build the macOS DAoC server from the pinned upstream + port overlay.
#
#   ./install-server.sh              -> server/dist/daoc-server/  (runnable server folder)
#
# Steps:
#   1. Fetch (or reuse) the pinned upstream archive and verify its SHA-256.
#   2. Unpack it into upstream/server/ (idempotent; reused between builds).
#   3. Install the .NET 10 SDK if missing (tools/setup-dotnet.sh).
#   4. Run the port's build pipeline (server/tools/build-release.sh), which applies the
#      macOS patches from server/patches/ and builds dist/daoc-server.
#
# Prerequisites: Xcode Command Line Tools, cmake (brew install cmake), curl, python3.
# Everything else is fetched automatically. Free tooling only.
set -euo pipefail
cd "$(dirname "$0")" && cd "$(pwd -P)"   # resolve symlinks: MSBuild must see one path

manifest_pin() { python3 -c "import json,sys; print(json.load(open('manifest.json'))['$1']['$2'])"; }

UPSTREAM_URL=$(manifest_pin server archive_url)
UPSTREAM_SHA=$(manifest_pin server archive_sha256)
UPSTREAM_REF=$(manifest_pin server ref)
ARCHIVE="downloads/daoc-offline-linux-server-bots-${UPSTREAM_REF:0:7}.tar.gz"
SRC_DIR="upstream/server"

echo "== install-server: pinned upstream ${UPSTREAM_REF:0:12}"

# 1. Fetch + verify the pinned archive (cached in downloads/, gitignored).
mkdir -p downloads upstream
if [[ ! -f $ARCHIVE ]]; then
  echo "== downloading upstream archive"
  curl -fsSL --retry 3 "$UPSTREAM_URL" -o "$ARCHIVE"
fi
actual=$(shasum -a 256 "$ARCHIVE" | cut -d' ' -f1)
if [[ $actual != "$UPSTREAM_SHA" ]]; then
  echo "install-server: upstream archive checksum mismatch" >&2
  echo "  expected $UPSTREAM_SHA" >&2
  echo "  actual   $actual" >&2
  exit 1
fi

# 2. Unpack once; keep the extracted tree for rebuilds (rsync-style refresh happens
#    inside the build script via its build/src snapshot).
if [[ ! -d $SRC_DIR ]]; then
  echo "== extracting upstream source"
  mkdir -p upstream/tmp
  tar -xzf "$ARCHIVE" -C upstream/tmp
  mv "upstream/tmp/daoc-offline-linux-server-bots-$UPSTREAM_REF" "$SRC_DIR"
  rm -rf upstream/tmp
fi

# 3. Toolchain: the port's own installer handles a missing .NET 10 SDK.
if ! command -v dotnet >/dev/null 2>&1 && [[ ! -x "$HOME/.dotnet/dotnet" ]]; then
  server/tools/setup-dotnet.sh
fi
command -v cmake >/dev/null 2>&1 || { echo "install-server: cmake missing (brew install cmake)" >&2; exit 1; }

# 4. Build. DAOC_SOURCE_REPO points the build script (and the DB fetcher it calls)
#    at the unpacked upstream instead of the default ../daoc-offline-linux-server-bots.
export DAOC_SOURCE_REPO="$PWD/$SRC_DIR"
server/tools/build-release.sh

echo "== install-server: done — server/dist/daoc-server"
echo "   start it:  cd server/dist/daoc-server && ./daoc-server.sh start"