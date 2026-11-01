"""The Game account in the login Keychain; never written anywhere else.

Service daoc-offline, accounts login_account and login_password. The password
is stored with a bare `-w` as the last argument: security then prompts for it
itself (no echo), so it is never on any argv.

Over SSH the login keychain stays locked even while it is unlocked in the GUI
session: macOS unlocks it only for the session you logged in to, and security
then fails with "User interaction is not allowed" (exit 36). That is not the
same as no saved account (exit 44). On a terminal daoc runs
`security unlock-keychain`, which prompts for the macOS login password itself;
off a terminal it says how to unlock.

From the OfflineDAoC app (DAOC_EVENTS) the account and password come in the
answer to a `secret` event. The password still goes to the bare `-w` prompt:
run in a new session (no controlling terminal), security reads it and its
confirmation from stdin, so it is never on argv.
"""
import sys
from typing import Optional, Tuple

from daoc_cli import events, proc
from daoc_cli.errors import DaocError, interactive, say

SECURITY = "/usr/bin/security"
SERVICE = "daoc-offline"
ACCOUNT = "login_account"
PASSWORD = "login_password"

# security's exit codes (the low byte of the OSStatus).
NOT_FOUND = 44     # errSecItemNotFound
LOCKED = 36        # errSecInteractionNotAllowed: the keychain is locked for this session


def saved() -> Optional[bool]:
    """Whether a Game account is saved, read without its secret (no -w): True,
    False, or None when the keychain is locked or security fails."""
    result = proc.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", ACCOUNT], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == NOT_FOUND:
        return False
    return None


class NotSaved(DaocError):
    """No Game account is saved."""

    def __init__(self) -> None:
        super().__init__("no saved game account; run daoc client login in Terminal", 2)


def _find(account: str) -> "proc.subprocess.CompletedProcess[str]":
    return proc.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
                    check=False)


def unlock() -> None:
    """Unlock the login keychain for this session; security asks for the password."""
    if not sys.stdin.isatty():
        raise DaocError("the login keychain is locked in this session (an SSH login does not "
                        "share the GUI's unlocked keychain); run `security unlock-keychain` "
                        "first, or run daoc from a Terminal on the Mac", 2)
    say("the login keychain is locked in this session (SSH logins don't share the "
        "GUI's unlocked keychain); unlocking it with your macOS login password")
    if proc.run([SECURITY, "unlock-keychain"], verbose=True, check=False).returncode != 0:
        raise DaocError("could not unlock the login keychain", 2)


def _value(account: str) -> str:
    """The saved secret for account; unlocks once when the keychain is locked."""
    result = _find(account)
    if result.returncode == LOCKED:
        unlock()
        result = _find(account)
    if result.returncode == NOT_FOUND:
        raise NotSaved()
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise DaocError(f"cannot read the game account from the Keychain: {detail or result.returncode}")
    return result.stdout.rstrip("\n")


def read() -> Tuple[str, str]:
    """(account, password); NotSaved when either is missing."""
    account, password = _value(ACCOUNT), _value(PASSWORD)
    if not account or not password:
        raise NotSaved()
    return account, password


def _from_app() -> Tuple[str, str]:
    """(account, password) from the app's answer to a `secret` event."""
    answer = events.request("secret", what="login") or {}
    account, password = answer.get("account"), answer.get("password")
    if not isinstance(account, str) or not account.strip():
        raise DaocError("no account name given", 2)
    if not isinstance(password, str) or not password:
        raise DaocError("no password given", 2)
    if "\n" in password or "\r" in password:
        raise DaocError("the password cannot contain a line break", 2)
    return account.strip(), password


def save_interactive() -> None:
    """Ask for the account name and password, on the terminal or from the app,
    and save (or replace) both."""
    if not interactive():
        raise DaocError("daoc client login needs a terminal", 2)
    password: Optional[str] = None
    if events.on():
        account, password = _from_app()
    else:
        try:
            print("Game account name: ", end="", file=sys.stderr, flush=True)
            account = input().strip()
        except EOFError:
            account = ""
    if not account:
        raise DaocError("no account name given", 2)
    # A locked keychain (SSH) refuses the write the same way it refuses a read.
    if _find(ACCOUNT).returncode == LOCKED:
        unlock()
    proc.run([SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", account])
    add_password = [SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", PASSWORD, "-w"]
    if password is None:
        # Bare -w last: security prompts for the password itself (no echo, not on argv).
        print("Game account password:", file=sys.stderr, flush=True)
        result = proc.run(add_password, verbose=True, check=False)
    else:
        result = proc.run(add_password, input=f"{password}\n{password}\n", new_session=True, check=False)
    if result.returncode != 0 or _find(PASSWORD).returncode != 0:
        raise DaocError("game account password not saved", 2)
