# admin-socket.sh - sourced by daoc-server.sh and daoc-admin: the admin socket's path.
#
# The socket lives in run/ next to the server, unless that path is too long for a
# unix socket (macOS: 104 bytes, sun_path), as it is under a deep data home such as
# ~/Library/Application Support/OfflineDAoC with a long user name. Then it is a short
# path in /tmp named for this folder, so every script finds the same socket.
admin_socket() {
  local LC_ALL=C
  local path="$1/run/admin.sock"
  if (( ${#path} > 100 )); then
    path="/tmp/daoc-$(id -u)-$(printf '%s' "$1" | cksum | cut -d' ' -f1).sock"
  fi
  printf '%s\n' "$path"
}
