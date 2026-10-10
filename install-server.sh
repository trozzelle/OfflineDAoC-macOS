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

# 1. Fetch the pinned upstream as a git clone, verify the exact commit, and
#    pre-check the port patches against it (a ref change or an upstream edit
#    that breaks a patch fails here, loudly, before any build time is spent).
UPSTREAM_URL=$(manifest_pin server upstream)
UPSTREAM_REF=$(manifest_pin server ref)
SRC_DIR="upstream/server"

echo "== install-server: pinned upstream ${UPSTREAM_REF:0:12}"
mkdir -p downloads upstream
if [[ ! -d $SRC_DIR/.git ]]; then
  echo "== cloning upstream (this downloads ~400 MB)"
  git clone --quiet "$UPSTREAM_URL" "$SRC_DIR"
fi
checked=$(git -C "$SRC_DIR" rev-parse HEAD)
if [[ $checked != "$UPSTREAM_REF" ]]; then
  echo "== checking out pinned ${UPSTREAM_REF:0:12} (have ${checked:0:12})"
  git -C "$SRC_DIR" fetch --quiet origin "$UPSTREAM_REF" 2>/dev/null || git -C "$SRC_DIR" fetch --quiet origin
  git -C "$SRC_DIR" checkout --quiet --detach "$UPSTREAM_REF"
fi
actual=$(git -C "$SRC_DIR" rev-parse HEAD)
[[ $actual == "$UPSTREAM_REF" ]] || { echo "install-server: upstream HEAD ${actual:0:12} != pinned ${UPSTREAM_REF:0:12}" >&2; exit 1; }

# Pre-check the macOS patches apply cleanly to this snapshot.
git -C "$SRC_DIR" apply --check "$PWD"/server/patches/*.patch \
  || { echo "install-server: patches no longer apply to the pinned upstream — re-derive them" >&2; exit 1; }
echo "== patches apply cleanly"

# 2. Toolchain: the port's own installer is idempotent and always safe to run.
server/tools/setup-dotnet.sh
command -v cmake >/dev/null 2>&1 || { echo "install-server: cmake missing (brew install cmake)" >&2; exit 1; }

# 4. Build. DAOC_SOURCE_REPO points the build script (and the DB fetcher it calls)
#    at the unpacked upstream instead of the default ../daoc-offline-linux-server-bots.
export DAOC_SOURCE_REPO="$PWD/$SRC_DIR"
server/tools/build-release.sh

echo "== install-server: done — server/dist/daoc-server"
echo "   start it:  cd server/dist/daoc-server && ./daoc-server.sh start"