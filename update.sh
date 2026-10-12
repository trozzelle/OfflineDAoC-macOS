#!/usr/bin/env bash
# update.sh - bump the pinned upstreams in manifest.json.
#
#   ./update.sh server          -> point the server pin at upstream's current HEAD
#   ./update.sh client          -> point the client pin at the latest OfflineDAoC release
#   ./update.sh graphics        -> point the graphics pin at OfflineDAoC-macOS-graphics' main
#   ./update.sh check           -> report what moved without changing anything
#
# Pins are deliberately manual: an update re-fetches and re-applies the overlay;
# if upstream changed in a way the patches no longer cover, the install fails
# loudly rather than silently producing a broken build.
set -euo pipefail
cd "$(dirname "$0")" && cd "$(pwd -P)"

cmd="${1:-check}"

latest_server_ref() {
  curl -fsSL "https://api.github.com/repos/catastrophic-impact/daoc-offline-linux-server-bots/commits/main" |
    python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])"
}

latest_client_version() {
  curl -fsSL "https://api.github.com/repos/shadowofze/OfflineDAoC/releases/latest" |
    python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))"
}

manifest_pin() { python3 -c 'import json, sys; print(json.load(open("manifest.json"))[sys.argv[1]][sys.argv[2]])' "$1" "$2"; }

# Resolve main from graphics.repo itself, so the sha always comes from the repo
# that update.sh and graphics.sh then clone.
latest_graphics_ref() {
  local repo slug
  repo=$(manifest_pin graphics repo)
  if [[ $repo != https://github.com/* ]]; then
    echo "update.sh: graphics.repo is not a https://github.com/ URL: $repo" >&2
    return 1
  fi
  slug=${repo#https://github.com/}
  slug=${slug%/}
  slug=${slug%.git}
  curl -fsSL "https://api.github.com/repos/$slug/commits/main" |
    python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])"
}

set_pin() {
  python3 - "$@" << 'EOF'
import json, sys
path, section, key, value = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
m = json.load(open(path))
m[section][key] = value
json.dump(m, open(path, "w"), indent=2)
EOF
}

case "$cmd" in
  check)
    cur_ref=$(manifest_pin server ref)
    cur_ver=$(manifest_pin client version)
    new_ref=$(latest_server_ref)
    new_ver=$(latest_client_version)
    echo "server : pinned ${cur_ref:0:12}   latest ${new_ref:0:12}   $([[ $cur_ref == $new_ref ]] && echo up-to-date || echo UPDATE AVAILABLE)"
    echo "client : pinned v$cur_ver        latest v$new_ver        $([[ $cur_ver == $new_ver ]] && echo up-to-date || echo UPDATE AVAILABLE)"
    cur_gfx=$(manifest_pin graphics ref)
    new_gfx=$(latest_graphics_ref)
    echo "graphics: pinned ${cur_gfx:0:12}   latest ${new_gfx:0:12}   $([[ $cur_gfx == $new_gfx ]] && echo up-to-date || echo UPDATE AVAILABLE)"
    ;;
  server)
    echo "== resolving upstream HEAD"
    new_ref=$(latest_server_ref)
    cur_ref=$(manifest_pin server ref)
    if [[ $new_ref == "$cur_ref" ]]; then
      echo "server pin already at ${new_ref:0:12}"; exit 0
    fi
    # Clone the new HEAD shallowly and prove the port patches still apply to it
    # BEFORE switching the pin — an upstream change that breaks a patch fails
    # here, loudly, and the pin stays put.
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    git clone --quiet --filter=blob:none "https://github.com/catastrophic-impact/daoc-offline-linux-server-bots" "$tmp/upstream" \
      || { echo "update.sh: upstream clone failed" >&2; exit 1; }
    git -C "$tmp/upstream" checkout --quiet --detach "$new_ref"
    if ! git -C "$tmp/upstream" apply --check "$PWD"/server/patches/*.patch; then
      echo "update.sh: port patches no longer apply to ${new_ref:0:12} — re-derive them against the new source" >&2
      echo "  (pin NOT changed: manifest.json still points at ${cur_ref:0:12})" >&2
      exit 1
    fi
    echo "== patches apply cleanly to ${new_ref:0:12}"
    set_pin manifest.json server ref "$new_ref"
    # The old extracted tree no longer matches the pin — clear it.
    rm -rf upstream/server
    echo "== server pin -> ${new_ref:0:12}"
    echo "   stop the server, then re-run ./install-server.sh to rebuild against the new source."
    echo "   if the update ships new world data: cd server/dist/daoc-server && ./daoc-progress upgrade"
    ;;
  client)
    echo "== resolving latest OfflineDAoC release"
    new_ver=$(latest_client_version)
    cur_ver=$(manifest_pin client version)
    if [[ $new_ver == "$cur_ver" ]]; then
      echo "client pin already at v$new_ver"; exit 0
    fi
    base="https://github.com/shadowofze/OfflineDAoC/releases/download/v$new_ver"
    # Cross-check the new release's manifest before pinning it.
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$base/download-manifest.json" -o "$tmp/manifest.json"
    python3 - "$tmp/manifest.json" "$new_ver" << 'EOF'
import json, sys
rm = json.load(open(sys.argv[1]))
version = sys.argv[2]
assert rm["Version"] == version, f"manifest version {rm['Version']!r} != {version!r}"
print("  release manifest OK:",
      f"{len(rm['Parts'])} parts, archive sha {rm['ArchiveSHA256'][:16]}…")
EOF
    set_pin manifest.json client version "$new_ver"
    set_pin manifest.json client release_url "$base/"
    set_pin manifest.json client root_folder "OfflineDAoC-v$new_ver"
    python3 - "$tmp/manifest.json" << 'EOF'
import json, sys
rm = json.load(open(sys.argv[1]))
m = json.load(open("manifest.json"))
m["client"]["archive_sha256"] = rm["ArchiveSHA256"]
m["client"]["archive_bytes"] = rm["ArchiveBytes"]
m["client"]["parts"] = [
    {"name": p["Name"], "bytes": p["Bytes"], "sha256": p["SHA256"]} for p in rm["Parts"]
]
# The pristine game.dll hash must be re-derived for a new release; clear it so
# install cannot silently patch an unknown base.
m["client"].pop("game_dll_sha256", None)
json.dump(m, open("manifest.json", "w"), indent=2)
print("  pinned client v" + sys.argv[2] + "; game_dll_sha256 cleared — "
      "re-derive it from the new release's game.dll before installing.")
EOF
    echo "== client pin -> v$new_ver"
    echo "   NOTE: verify the new release's game.dll hash and set client.game_dll_sha256,"
    echo "   then re-run ./install-client.sh."
    ;;
  graphics)
    echo "== resolving OfflineDAoC-macOS-graphics main"
    new_ref=$(latest_graphics_ref)
    cur_ref=$(manifest_pin graphics ref)
    if [[ $new_ref == "$cur_ref" ]]; then
      echo "graphics pin already at ${new_ref:0:12}"; exit 0
    fi
    # Run the new commit's own tests before switching the pin; a failing
    # commit leaves the pin where it was.
    repo=$(manifest_pin graphics repo)
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    git clone --quiet "$repo" "$tmp/graphics" \
      || { echo "update.sh: graphics clone failed" >&2; exit 1; }
    git -C "$tmp/graphics" checkout --quiet --detach "$new_ref"
    # Captured, not discarded: replay it on failure (the clone is deleted), and
    # surface skips on success (test_sampler skips its C test without cc).
    if ! (cd "$tmp/graphics" && python3 -m unittest discover -v -s tests >"$tmp/tests.log" 2>&1); then
      cat "$tmp/tests.log" >&2
      echo "update.sh: graphics tests fail at ${new_ref:0:12}; pin unchanged" >&2
      exit 1
    fi
    grep -E '\.\.\. skipped' "$tmp/tests.log" >&2 || true
    echo "== graphics tests pass at ${new_ref:0:12}"
    # The contract the tests can't see: graphics.sh passes --app/--wine/--prefix
    # and defaults to select, and the anisotropy patch rewrites
    # client/DAoCLauncher.app's WINEDLLOVERRIDES line only if it matches
    # STOCK_LINE exactly once.
    help=$(python3 "$tmp/graphics/daoc-gfx" --help 2>&1) || help=
    for word in --app --wine --prefix select; do
      if ! grep -qE -- "(^|[^-[:alnum:]_])$word([^-[:alnum:]_]|\$)" <<<"$help"; then
        echo "update.sh: daoc-gfx --help at ${new_ref:0:12} no longer lists $word, which graphics.sh relies on; pin unchanged" >&2
        exit 1
      fi
    done
    if ! python3 - "$tmp/graphics" client/DAoCLauncher.app/Contents/MacOS/launch <<'EOF'
import sys
sys.path.insert(0, sys.argv[1])
from daoc_gfx.anisotropy import STOCK_LINE
lines = [line.strip() for line in open(sys.argv[2], encoding="utf-8").read().splitlines()]
sys.exit(lines.count(STOCK_LINE) != 1)
EOF
    then
      echo "update.sh: the anisotropy patch at ${new_ref:0:12} no longer matches client/DAoCLauncher.app's WINEDLLOVERRIDES line; pin unchanged" >&2
      exit 1
    fi
    echo "== daoc-gfx options and launcher line match at ${new_ref:0:12}"
    set_pin manifest.json graphics ref "$new_ref"
    echo "== graphics pin -> ${new_ref:0:12}"
    echo "   the next ./graphics.sh call checks it out."
    ;;
  *)
    echo "usage: update.sh server|client|graphics|check" >&2
    exit 2
    ;;
esac