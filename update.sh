#!/usr/bin/env bash
# update.sh - bump the pinned upstreams in manifest.json.
#
#   ./update.sh server          -> point the server pin at upstream's current HEAD
#   ./update.sh client          -> point the client pin at the latest OfflineDAoC release
#   ./update.sh check           -> report what moved without changing anything
#
# Pins are deliberately manual: an update re-fetches and re-applies the overlay;
# if upstream changed in a way the patches no longer cover, the install fails
# loudly rather than silently producing a broken build.
set -euo pipefail
cd "$(dirname "$0")"

cmd="${1:-check}"

latest_server_ref() {
  curl -fsSL "https://api.github.com/repos/catastrophic-impact/daoc-offline-linux-server-bots/commits/main" |
    python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])"
}

latest_client_version() {
  curl -fsSL "https://api.github.com/repos/shadowofze/OfflineDAoC/releases/latest" |
    python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))"
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
    cur_ref=$(python3 -c "import json; print(json.load(open('manifest.json'))['server']['ref'])")
    cur_ver=$(python3 -c "import json; print(json.load(open('manifest.json'))['client']['version'])")
    new_ref=$(latest_server_ref)
    new_ver=$(latest_client_version)
    echo "server : pinned ${cur_ref:0:12}   latest ${new_ref:0:12}   $([[ $cur_ref == $new_ref ]] && echo up-to-date || echo UPDATE AVAILABLE)"
    echo "client : pinned v$cur_ver        latest v$new_ver        $([[ $cur_ver == $new_ver ]] && echo up-to-date || echo UPDATE AVAILABLE)"
    ;;
  server)
    echo "== resolving upstream HEAD"
    new_ref=$(latest_server_ref)
    cur_ref=$(python3 -c "import json; print(json.load(open('manifest.json'))['server']['ref'])")
    if [[ $new_ref == "$cur_ref" ]]; then
      echo "server pin already at ${new_ref:0:12}"; exit 0
    fi
    # Fetch the new archive once to record its hash before switching the pin.
    url="https://codeload.github.com/catastrophic-impact/daoc-offline-linux-server-bots/tar.gz/$new_ref"
    archive="downloads/daoc-offline-linux-server-bots-${new_ref:0:7}.tar.gz"
    mkdir -p downloads
    curl -fsSL --retry 3 "$url" -o "$archive"
    sha=$(shasum -a 256 "$archive" | cut -d' ' -f1)
    set_pin manifest.json server ref "$new_ref"
    set_pin manifest.json server archive_url "$url"
    set_pin manifest.json server archive_sha256 "$sha"
    # The old extracted tree no longer matches the pin — clear it.
    rm -rf upstream/server
    echo "== server pin -> ${new_ref:0:12} (archive sha256 $sha)"
    echo "   re-run ./install-server.sh to rebuild; if a patch no longer applies,"
    echo "   the build fails loudly — re-derive the patch against the new source."
    ;;
  client)
    echo "== resolving latest OfflineDAoC release"
    new_ver=$(latest_client_version)
    cur_ver=$(python3 -c "import json; print(json.load(open('manifest.json'))['client']['version'])")
    if [[ $new_ver == "$cur_ver" ]]; then
      echo "client pin already at v$new_ver"; exit 0
    fi
    base="https://github.com/shadowofze/OfflineDAoC/releases/download/v$new_ver"
    # Cross-check the new release's manifest before pinning it.
    tmp=$(mktemp -d)
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
    rm -rf "$tmp"
    echo "== client pin -> v$new_ver"
    echo "   NOTE: verify the new release's game.dll hash and set client.game_dll_sha256,"
    echo "   then re-run ./install-client.sh."
    ;;
  *)
    echo "usage: update.sh server|client|check" >&2
    exit 2
    ;;
esac