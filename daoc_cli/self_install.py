"""`daoc self-install`: put a `daoc` wrapper for this Checkout on PATH.

The wrapper is a small sh file at ~/.local/bin/daoc with the Checkout path
baked in, not a symlink: when the Checkout moves or is deleted the
wrapper says so, names the fix and exits 127. A file there that lacks MARKER is
not ours and is never replaced. If ~/.local/bin is not on PATH, a tty user is
offered the PATH line in ~/.zprofile (default no); otherwise it is only printed.
"""
import argparse
import os
import shlex
import sys
import tempfile
from pathlib import Path

from daoc_cli.errors import DaocError

MARKER = "# daoc wrapper written by daoc self-install"
PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"'


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "self-install",
        help="write the ~/.local/bin/daoc wrapper for this checkout",
        description="Write ~/.local/bin/daoc, a sh wrapper that runs this checkout's ./daoc.",
    )
    p.set_defaults(func=handle)


def wrapper_text(root: Path) -> str:
    q = shlex.quote(str(root))
    return (
        "#!/bin/sh\n"
        f"{MARKER}\n"
        f"CHECKOUT={q}\n"
        'if [ ! -x "$CHECKOUT/daoc" ]; then\n'
        f"    echo {shlex.quote(f'daoc: checkout {root} is gone (moved or deleted); run ./daoc self-install from its new location')} >&2\n"
        "    exit 127\n"
        "fi\n"
        'exec "$CHECKOUT/daoc" "$@"\n'
    )


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".daoc.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o755)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _ours(path: Path) -> bool:
    try:
        with open(path, "r", errors="replace") as f:
            head = f.read(4096)
    except OSError:
        return False
    return MARKER in head.splitlines()


def _on_path(bin_dir: Path) -> bool:
    want = os.path.realpath(str(bin_dir))
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and os.path.realpath(os.path.expanduser(entry)) == want:
            return True
    return False


def _offer_path(home: Path) -> None:
    profile = home / ".zprofile"
    if not sys.stdin.isatty():
        print("~/.local/bin is not on PATH. Add this line to your shell profile (e.g. ~/.zprofile):",
              file=sys.stderr)
        print(f"  {PATH_LINE}", file=sys.stderr)
        return
    print("Add ~/.local/bin to PATH in ~/.zprofile? [y/N] ", end="", file=sys.stderr, flush=True)
    answer = sys.stdin.readline().strip().lower()
    if answer not in ("y", "yes"):
        print(f"Not changed. To do it yourself, add: {PATH_LINE}", file=sys.stderr)
        return
    existing = profile.read_text() if profile.exists() else ""
    if PATH_LINE in existing.splitlines():
        print(f"{profile} already has the PATH line", file=sys.stderr)
        return
    with open(profile, "a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(PATH_LINE + "\n")
    print(f"Appended the PATH line to {profile}; open a new shell to use it", file=sys.stderr)


def handle(args: argparse.Namespace, checkout) -> int:
    root = Path(os.path.realpath(str(checkout.root)))
    home = Path.home()
    bin_dir = home / ".local" / "bin"
    target = bin_dir / "daoc"
    if (target.exists() or target.is_symlink()) and (target.is_symlink() or not _ours(target)):
        raise DaocError(f"{target} exists and was not written by daoc self-install; "
                        "move it aside and re-run", code=2)
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(target, wrapper_text(root))
    print(f"Wrote {target} -> {root}/daoc", file=sys.stderr)
    if not _on_path(bin_dir):
        _offer_path(home)
    return 0
