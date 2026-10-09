#!/usr/bin/env bash
# daoc-server.sh - run a portable DAoC server folder on macOS. Everything lives next to this
# script, so the folder can be unpacked or moved anywhere. No .NET install is needed: bin/ is
# self-contained.
#
#   ./daoc-server.sh start            start the server in the background and open the admin
#                                     screen here (quit it with Ctrl+Q: stop the server or leave it running)
#   ./daoc-server.sh start --console  raw server console in the foreground instead (Ctrl+C, SIGTERM
#                                     or "exit" stop it); also used automatically without a terminal
#   ./daoc-server.sh stop      stop a running server cleanly (saves first)
#   ./daoc-server.sh status    is it running?
#   ./daoc-admin               manage bots, population and accounts (terminal GUI or commands)
#
# Folder layout:
#   bin/        server program (replaced on upgrade)
#   defaults/   templates copied into config/ on first start
#   config/     serverconfig.xml, logconfig.xml, invalidnames.txt   (yours; kept on upgrade)
#   data/       opendaoc.sqlite3.db: the world and all saves (yours; kept on upgrade). Created on
#               first start from defaults/world.sqlite, a fresh Classic + SI world.
#   navmesh/    zone*.nav, from ./navmesh-install.sh                  (kept on upgrade)
#   logs/  run/
#
# macOS port of the Linux repo's deploy/daoc-server.sh. Differences:
#   - ICU check: macOS ships libicu as part of the system since Sonoma 14.x; on older systems the
#     bundled .NET runtime carries its own ICU fallback, so no ldconfig-style check is needed.
#   - Port probe uses nc (no /dev/tcp on bash from Homebrew; /dev/tcp works in /bin/bash but nc
#     is more predictable across bash builds).
#   - setsid does not exist on macOS: the server is detached with nohup + disown instead (own
#     process group via POSIX process groups is not needed since the script only signals by PID).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAOC_HOME="${DAOC_HOME:-$HERE}"
PIDFILE="$DAOC_HOME/run/server.pid"

die() { echo "daoc-server: $*" >&2; exit 1; }

running_pid() {
  local pid
  [[ -f $PIDFILE ]] || return 1
  pid=$(<"$PIDFILE")
  [[ $pid =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null && echo "$pid"
}

# The game port from config/serverconfig.xml (10300 if not set yet).
game_port() {
  local port
  port=$(sed -n 's:.*<Port>\([0-9]*\)</Port>.*:\1:p' "$DAOC_HOME/config/serverconfig.xml" 2>/dev/null | head -1)
  echo "${port:-10300}"
}

port_in_use() { nc -z -w 1 127.0.0.1 "$(game_port)" >/dev/null 2>&1; }

start() {
  local mode=${1:-}
  # --console, or no terminal (init system, redirect): run the raw server console in the foreground.
  local console=false
  [[ $mode == --console || ! -t 0 || ! -t 1 ]] && console=true

  if running_pid >/dev/null; then
    $console && die "already running (pid $(running_pid))"
    exec "$DAOC_HOME/daoc-admin"   # already running: just open the admin screen
  fi
  [[ -x $DAOC_HOME/bin/CoreServer ]] || die "no server program in $DAOC_HOME/bin"
  compgen -G "$DAOC_HOME/navmesh/*.nav" >/dev/null || die "no navmeshes yet. Run ./navmesh-install.sh (see README.md)"

  mkdir -p "$DAOC_HOME"/{config,data,logs,run}
  if [[ ! -f $DAOC_HOME/data/opendaoc.sqlite3.db ]]; then
    echo "First start: creating a fresh world in data/opendaoc.sqlite3.db"
    cp "$DAOC_HOME/defaults/world.sqlite" "$DAOC_HOME/data/opendaoc.sqlite3.db"
  fi
  for f in serverconfig.xml logconfig.xml invalidnames.txt; do
    [[ -e $DAOC_HOME/config/$f ]] || cp "$DAOC_HOME/defaults/$f" "$DAOC_HOME/config/"
  done
  ! port_in_use || die "port $(game_port) is already in use (another server is running; see <Port> in config/serverconfig.xml)"

  # The admin socket (used by ./daoc-admin) lives in run/.
  export DAOC_ADMIN_SOCKET="$DAOC_HOME/run/admin.sock"
  cd "$DAOC_HOME/bin"

  if $console; then
    echo $$ > "$PIDFILE"
    # exec keeps this PID, so the pid file and signals reach the server itself.
    exec ./CoreServer --start "-config=$DAOC_HOME/config/serverconfig.xml"
  fi

  # Default: server in the background (nohup so closing this terminal does not stop it),
  # then the admin screen in this terminal.
  local log="$DAOC_HOME/logs/console.out" pid i
  [[ -f $log ]] && mv -f "$log" "$DAOC_HOME/logs/console.prev.out"
  nohup ./CoreServer --start "-config=$DAOC_HOME/config/serverconfig.xml" </dev/null >"$log" 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > "$PIDFILE"
  printf 'Starting server (pid %s)' "$pid"
  for ((i = 0; i < 180; i++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo; echo "The server did not start. Last lines of $log:" >&2
      tail -n 25 "$log" >&2
      rm -f "$PIDFILE"
      exit 1
    fi
    [[ -S $DAOC_ADMIN_SOCKET ]] && grep -q "Server is now listening" "$log" && break
    printf '.'
    sleep 1
  done
  echo
  exec "$DAOC_HOME/daoc-admin"
}

stop() {
  local pid i
  pid=$(running_pid) || { echo "not running"; return 0; }
  kill -TERM "$pid"
  for ((i = 0; i < 120; i++)); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$PIDFILE"; echo "stopped"; return 0; }
    sleep 1
  done
  die "server (pid $pid) did not stop within 120 s"
}

case "${1:-}" in
  start)  start "${2:-}" ;;
  stop)   stop ;;
  status) if pid=$(running_pid); then echo "running (pid $pid)"; else echo "stopped"; fi ;;
  *) echo "usage: $0 start [--console] | stop | status"; exit 2 ;;
esac