"""`daoc server`: build the macOS server, and start/stop/status it.

install ports the old install-server.sh step for step:
  1. Clone (or reuse) the pinned upstream in upstream/server/, verify the exact
     commit, and pre-check the port patches against it.
  2. Install the .NET 10 SDK if missing (server/tools/setup-dotnet.sh).
  3. Run the port's build pipeline (server/tools/build-release.sh), which applies
     the macOS patches from server/patches/ and builds server/dist/daoc-server.

start/stop/status exec the install's own daoc-server.sh, which stays shell.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from daoc_cli import pins, proc
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

NO_INSTALL = "no Server install; run daoc server install"


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "server",
        help="install, run and update the local OpenDAoC server",
        description="Install, run and update the local OpenDAoC server.",
    )
    actions = p.add_subparsers(dest="action", title="actions")
    a = actions.add_parser("install", help="build server/dist/daoc-server from the pinned upstream")
    a.add_argument("-v", "--verbose", action="store_true",
                   help="show git progress and the build's warnings and tool output")
    a.set_defaults(func=_handle_install)
    a = actions.add_parser("start", help="start the server (daoc-server.sh start)")
    a.add_argument("--console", action="store_true", help="run in the foreground with its console")
    a.set_defaults(func=_handle_script)
    for name, text in (("stop", "stop the server"), ("status", "print running (pid N) or stopped")):
        actions.add_parser(name, help=text).set_defaults(func=_handle_script)


def _handle_install(args: argparse.Namespace, checkout: Checkout) -> int:
    install(checkout, verbose=args.verbose)
    return 0


def _handle_script(args: argparse.Namespace, checkout: Checkout) -> int:
    argv: List[str] = [str(script(checkout)), args.action]
    if getattr(args, "console", False):
        argv.append("--console")
    proc.execv(argv, cwd=checkout.server_dir)


def script(checkout: Checkout) -> Path:
    """<server_dir>/daoc-server.sh; DaocError when there is no Server install."""
    path = checkout.server_dir / "daoc-server.sh"
    if not path.is_file():
        raise DaocError(NO_INSTALL)
    return path


def tool(checkout: Checkout, name: str) -> Path:
    """An executable in the Server install (daoc-admin, daoc-progress)."""
    path = checkout.server_dir / name
    if not checkout.server_dir.is_dir() or not path.is_file():
        raise DaocError(NO_INSTALL)
    return path


def status(checkout: Checkout) -> Tuple[Optional[bool], str]:
    """(running, detail). daoc-server.sh status exits 0 either way and prints
    `running (pid N)` or `stopped` (the detail); any other exit means it could
    not tell: running is None and detail says why. No install: (False, "stopped")."""
    path = checkout.server_dir / "daoc-server.sh"
    if not path.is_file():
        return False, "stopped"
    try:
        result = proc.run([path, "status"], cwd=checkout.server_dir, check=False)
    except DaocError as e:
        return None, e.msg
    if result.returncode != 0:
        return None, f"daoc-server.sh status exit {result.returncode}"
    out = result.stdout.strip()
    return out.startswith("running"), out


def running(checkout: Checkout) -> Optional[bool]:
    """True/False from daoc-server.sh status; None when unknown."""
    return status(checkout)[0]


def _git(args: List[str], src: Path, verbose: bool, **kw) -> "subprocess.CompletedProcess[str]":
    return proc.run(["git", "-C", str(src), *args], verbose=verbose, **kw)


def _head(src: Path) -> str:
    return proc.run(["git", "-C", str(src), "rev-parse", "HEAD"]).stdout.strip()


def install(checkout: Checkout, verbose: bool = False) -> None:
    # Resolve symlinks: MSBuild must see one path (the old script's `cd "$(pwd -P)"`).
    root = Path(os.path.realpath(checkout.root))
    progress = "--progress" if verbose else "--quiet"
    pin = pins.effective(checkout, "server")
    url, ref = pin["upstream"], pin["ref"]
    src = root / "upstream" / "server"

    # 1. Fetch the pinned upstream as a git clone, verify the exact commit, and
    #    pre-check the port patches against it (a ref change or an upstream edit
    #    that breaks a patch fails here, loudly, before any build time is spent).
    print(f"== install-server: pinned upstream {ref[:12]}", file=sys.stderr)
    (root / "downloads").mkdir(parents=True, exist_ok=True)
    (root / "upstream").mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not (src / ".git").is_dir():
        # Tarball-era extract (pre-git pinning): replace it with a proper clone.
        print("== replacing tarball-era upstream extract with a git clone", file=sys.stderr)
        shutil.rmtree(src)
    if not (src / ".git").is_dir():
        print("== cloning upstream (this downloads ~400 MB)", file=sys.stderr)
        proc.run(["git", "clone", progress, url, str(src)], verbose=True)
    checked = _head(src)
    if checked != ref:
        print(f"== checking out pinned {ref[:12]} (have {checked[:12]})", file=sys.stderr)
        # Fetching a bare sha can be refused by the server; fall back to a full fetch.
        # Its error is only shown with --verbose, as before.
        if _git(["fetch", progress, "origin", ref], src, verbose, check=False).returncode != 0:
            _git(["fetch", progress, "origin"], src, True)
        _git(["checkout", progress, "--detach", ref], src, True)
    actual = _head(src)
    if actual != ref:
        raise DaocError(f"upstream HEAD {actual[:12]} != pinned {ref[:12]}")

    # Pre-check the macOS patches apply cleanly to this snapshot.
    patches = sorted(str(p) for p in (root / "server" / "patches").glob("*.patch"))
    if _git(["apply", "--check", *patches], src, True, check=False).returncode != 0:
        raise DaocError("patches no longer apply to the pinned upstream — re-derive them")
    print("== patches apply cleanly", file=sys.stderr)

    # 2. Toolchain: the port's own installer is idempotent and always safe to run.
    print("== .NET 10 SDK (installed into ~/.dotnet if missing)", file=sys.stderr)
    proc.run([root / "server" / "tools" / "setup-dotnet.sh"], cwd=root, verbose=verbose)
    if shutil.which("cmake") is None:
        raise DaocError("cmake missing (brew install cmake)")

    # 3. Build. Pin DAOC_SOURCE_REPO to the clone verified above so the build (and the DB
    #    fetcher it calls) can't pick up a different tree from an inherited environment.
    env = dict(os.environ, DAOC_SOURCE_REPO=str(src))
    build = [str(root / "server" / "tools" / "build-release.sh")]
    if verbose:
        build.append("--verbose")
    proc.run(build, cwd=root, env=env, verbose=True)

    print("== install-server: done — server/dist/daoc-server", file=sys.stderr)
    print("   start it:  daoc server start", file=sys.stderr)
