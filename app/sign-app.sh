#!/bin/bash
# sign-app.sh APP IDENTITY [ENTITLEMENTS] - Developer ID signature, hardened runtime,
# inside out: every Mach-O under Resources, the nested launcher bundle, then the app.
set -euo pipefail

app=$1
identity=$2
entitlements=${3:-}

sign() { codesign --force --options runtime --timestamp --sign "$identity" "$@"; }

find "$app/Contents/Resources" -type f -print0 | while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q 'Mach-O'; then sign "$f"; fi
done
sign "$app/Contents/Resources/daoc/client/DAoCLauncher.app"
if [[ -n $entitlements ]]; then
  sign --entitlements "$entitlements" "$app"
else
  sign "$app"
fi
codesign --verify --deep --strict "$app"
