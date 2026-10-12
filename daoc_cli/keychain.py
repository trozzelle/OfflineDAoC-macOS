"""The Game account in the login Keychain; never written anywhere else.

Service daoc-offline, accounts login_account and login_password. The password
is stored with a bare `-w` as the last argument: security then prompts for it
itself (no echo), so it is never on any argv.
"""
import sys
from typing import Tuple

from daoc_cli import proc
from daoc_cli.errors import DaocError

SECURITY = "/usr/bin/security"
SERVICE = "daoc-offline"
ACCOUNT = "login_account"
PASSWORD = "login_password"


def _find(account: str) -> str:
    result = proc.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
                      check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\n")


def read() -> Tuple[str, str]:
    """(account, password); DaocError(2) when either is not saved."""
    account, password = _find(ACCOUNT), _find(PASSWORD)
    if not account or not password:
        raise DaocError("no saved game account; run daoc client login in Terminal", 2)
    return account, password


def save_interactive() -> None:
    """Ask for the account name and password and save (or replace) both."""
    if not sys.stdin.isatty():
        raise DaocError("daoc client login needs a terminal", 2)
    try:
        print("Game account name: ", end="", file=sys.stderr, flush=True)
        account = input().strip()
    except EOFError:
        account = ""
    if not account:
        raise DaocError("no account name given", 2)
    proc.run([SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", account])
    # Bare -w last: security prompts for the password itself (no echo, not on argv).
    print("Game account password:", file=sys.stderr, flush=True)
    result = proc.run([SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", PASSWORD, "-w"],
                      verbose=True, check=False)
    if result.returncode != 0 or not _find(PASSWORD):
        raise DaocError("game account password not saved", 2)
