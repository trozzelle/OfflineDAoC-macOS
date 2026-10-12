#!/bin/sh
# Renamed; this stub goes away in the next release.
case "${1:-check}" in
  server|client|graphics) echo "renamed: use daoc $1 update" >&2 ;;
  *) echo 'renamed: use daoc server update --check, daoc client update --check, daoc graphics update --check' >&2 ;;
esac
exit 2
