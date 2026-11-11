#!/bin/bash
# dev-run.sh [--fresh] - build OfflineDAoC.app from this checkout and open it on a test data folder.
#
#   app/dev-run.sh           build, sign ad hoc, open (the test install is kept between runs)
#   app/dev-run.sh --fresh   stop the test server, delete the test data folder, then the same:
#                            Setup starts from nothing
#
# The test data folder is $DAOC_DEV_DATA, default ~/Library/Application Support/OfflineDAoC-dev,
# passed to the app for this launch only (-dataHome), so the app's real data folder and this
# checkout's own installs are never touched. Release caches in this checkout's downloads/ are
# cloned into it (APFS copy-on-write: no disk space, no download). The Game account in the
# Keychain is shared with the daoc CLI: Setup's account step replaces it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo="$(cd "$here/.." && pwd -P)"
data="${DAOC_DEV_DATA:-$HOME/Library/Application Support/OfflineDAoC-dev}"
app="$here/dist/OfflineDAoC.app"

case "${1:-}" in
  "") ;;
  --fresh)
    server="$data/server/dist/daoc-server/daoc-server.sh"
    if [[ -x $server ]]; then "$server" stop; fi
    rm -rf "$data"
    ;;
  *) echo "usage: app/dev-run.sh [--fresh]" >&2; exit 2 ;;
esac

"$here/build-app.sh" "$here/dist"
"$here/sign-app.sh" "$app" -

mkdir -p "$data/downloads"
for cache in "$repo"/downloads/*; do
  [[ -e $cache && ! -e $data/downloads/$(basename "$cache") ]] || continue
  cp -Rc "$cache" "$data/downloads/"
done

echo "data folder: $data"
open -n "$app" --args -dataHome "$data"
