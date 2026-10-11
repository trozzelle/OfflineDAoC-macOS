#!/bin/zsh
# set-credentials.sh — store the game account used by launch-client.sh and
# bench-run.sh in your login Keychain (service "daoc-offline").
#   client/tools/set-credentials.sh [account]
# The password is prompted for by `security` itself (hidden input), so it never
# appears on a command line or in shell history. Re-running replaces the entry.
set -e
acct="${1:-}"
[ -n "$acct" ] || { printf 'Account name: '; read -r acct; }
[ -n "$acct" ] || { echo "no account name given" >&2; exit 1; }
/usr/bin/security add-generic-password -U -s daoc-offline -a login_account -w "$acct"
echo "Password for $acct (asked twice, not shown):"
/usr/bin/security add-generic-password -U -s daoc-offline -a login_password -w
echo "Stored. Check: security find-generic-password -s daoc-offline -a login_account -w"
