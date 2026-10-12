"""`daoc server`: build the macOS server, and start/stop/status it.

install:
  1. Clone (or reuse) the pinned upstream in upstream/server/, verify the exact
     commit, and pre-check the port patches against it.
  2. Install the .NET 10 SDK if missing (server/tools/setup-dotnet.sh).
  3. Run the port's build pipeline (server/tools/build-release.sh), which applies
     the macOS patches from server/patches/ and builds server/dist/daoc-server,
     then record the pin it was built from in the install (pins.INSTALLED).

start/stop/status exec the install's own daoc-server.sh, which stays shell.

update moves the install to upstream's latest after a patch pre-check, then
rebuilds and records it as the Local pin (see update()).
"""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import files, pins, proc, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, ask

NO_INSTALL = "no Server install; run daoc server install"

# The World data a build ships: build-release.sh's WorldBuilder writes it to
# <server_dir>/defaults/world.sqlite, and daoc-server.sh copies it into data/
# only on the first start, so an existing save keeps the world it was made with.
WORLD_DATA = Path("defaults") / "world.sqlite"


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
    a = actions.add_parser(
        "update",
        help="move the server to its upstream's latest commit and rebuild (Local pin)",
        description="Resolve the upstream's latest main commit, pre-check the port patches "
                    "against it, record it as a Local pin and rebuild the Server install.",
    )
    a.add_argument("--check", action="store_true",
                   help="report Shipped, Local, built-from and latest; change nothing")
    a.set_defaults(func=_handle_update)
    a = actions.add_parser("start", help="start the server (daoc-server.sh start)")
    a.add_argument("--console", action="store_true", help="run in the foreground with its console")
    a.set_defaults(func=_handle_script)
    for name, text in (("stop", "stop the server"), ("status", "print running (pid N) or stopped")):
        actions.add_parser(name, help=text).set_defaults(func=_handle_script)


def _handle_install(args: argparse.Namespace, checkout: Checkout) -> int:
    install(checkout, verbose=args.verbose)
    return 0


def _handle_update(args: argparse.Namespace, checkout: Checkout) -> int:
    if args.check:
        return updates.check(checkout, "server")
    return update(checkout)


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


def install(checkout: Checkout, verbose: bool = False,
            pin: Optional[Dict[str, Any]] = None) -> None:
    """Build the Server install from pin (default: the effective server pin)."""
    # Resolve symlinks: MSBuild must see one path (the old script's `cd "$(pwd -P)"`).
    root = Path(os.path.realpath(checkout.root))
    progress = "--progress" if verbose else "--quiet"
    pin = pin if pin is not None else pins.effective(checkout, "server")
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
    checked = proc.head(src)
    if checked != ref:
        print(f"== checking out pinned {ref[:12]} (have {checked[:12]})", file=sys.stderr)
        # Fetching a bare sha can be refused by the server; fall back to a full fetch.
        # Its error is only shown with --verbose, as before.
        if proc.git(src, "fetch", progress, "origin", ref, verbose=verbose,
                    check=False).returncode != 0:
            proc.git(src, "fetch", progress, "origin", verbose=True)
        proc.git(src, "checkout", progress, "--detach", ref, verbose=True)
    actual = proc.head(src)
    if actual != ref:
        raise DaocError(f"upstream HEAD {actual[:12]} != pinned {ref[:12]}")

    # Pre-check the macOS patches apply cleanly to this snapshot.
    patches = [str(p) for p in _patches(root)]
    if proc.git(src, "apply", "--check", *patches, verbose=True, check=False).returncode != 0:
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
    # A build that stops halfway leaves an install built from no pin.
    pins.forget_installed(checkout, "server")
    proc.run(build, cwd=root, env=env, verbose=True)
    pins.record_installed(checkout, "server", pin)

    print("== install-server: done — server/dist/daoc-server", file=sys.stderr)
    print("   start it:  daoc server start", file=sys.stderr)


def _patches(root: Path) -> List[Path]:
    """server/patches/*.patch in the order build-release.sh applies them."""
    return sorted((root / "server" / "patches").glob("*.patch"))


def _world_hash(checkout: Checkout) -> Optional[str]:
    path = checkout.server_dir / WORLD_DATA
    if not path.is_file():
        return None
    return files.sha256(path)


def _precheck(url: str, ref: str, patches: List[Path], current: str) -> None:
    """Clone ref into a temp dir and prove every port patch still applies, in
    build order, each on top of the ones before it. Nothing outside the temp
    dir is touched, so a failure leaves the pin where it was."""
    with tempfile.TemporaryDirectory(prefix="daoc-server-update-") as tmp:
        src = Path(tmp) / "upstream"
        print(f"== cloning upstream at {ref[:12]} to pre-check the port patches", file=sys.stderr)
        if proc.run(["git", "clone", "--quiet", "--filter=blob:none", url, str(src)],
                    check=False).returncode != 0:
            raise DaocError("upstream clone failed")
        proc.git(src, "checkout", "--quiet", "--detach", ref)
        for patch in patches:
            if proc.git(src, "apply", "--check", str(patch), check=False).returncode != 0:
                raise DaocError(
                    f"{patch.name} no longer applies to {ref[:12]}; re-derive it against the "
                    f"new source (pin not changed: still {current[:12]})"
                )
            proc.git(src, "apply", str(patch))
    print(f"== patches apply cleanly to {ref[:12]}", file=sys.stderr)


def _stop_first(checkout: Checkout) -> None:
    """The build refuses to replace bin/ under a live server: stop it, but
    only after asking on a terminal. Off a terminal, refuse."""
    state, detail = status(checkout)
    if state is False:
        return
    if state is None:
        raise DaocError(f"cannot tell whether the server is running ({detail}); "
                        "stop it first (daoc server stop)", 2)
    if not sys.stdin.isatty():
        raise DaocError("the server is running; stop it first (daoc server stop)", 2)
    if not ask(f"The server is {detail}. Stop it to update?"):
        raise DaocError("server update refused: the server is running", 2)
    proc.run([script(checkout), "stop"], cwd=checkout.server_dir, verbose=True)
    if running(checkout) is not False:
        raise DaocError("the server is still running after daoc-server.sh stop")


PROGRESS_UPGRADE = """\
The new build ships different World data ({world}).
Your save in data/ keeps the world it was created with until a Progress upgrade
moves your progress into the new world. It carries over the player-owned
things: accounts (roles kept), characters, items, money, houses, guilds and
bots, plus this install's settings (edition, population, daoc-admin options,
XP rates). Realm-wide world state such as keep and relic ownership starts
fresh. The previous save is backed up to data/progress-backups/<time>/."""


def update(checkout: Checkout) -> int:
    """Move the Server install to the upstream's latest main and rebuild it,
    recording that commit as the Local pin unless the pin already names it. Exit 0
    (updated, or the install already built from latest); DaocError 1 on a
    failing patch or build, 2 when stopping the server is refused."""
    from daoc_cli import overview  # overview imports this module

    root = Path(os.path.realpath(checkout.root))

    # 1. Resolve the upstream's latest main. Whether the install is already there
    #    is read from the install, not the pin: a pull can move the pin alone.
    print("== resolving upstream main", file=sys.stderr)
    current = pins.effective(checkout, "server")
    latest = updates.resolve_latest(checkout, "server")
    if overview._built_from(checkout, "server", latest)[1]:
        print(f"server already at {latest['ref'][:12]}", file=sys.stderr)
        return 0

    # 2. Clone the new commit (blobless) and prove the port patches still apply to
    #    it BEFORE moving the pin: an upstream change that breaks a patch fails
    #    here, loudly, and the pin stays put.
    _precheck(latest["upstream"], latest["ref"], _patches(root), current["ref"])

    # 3. Never rebuild under a live server.
    _stop_first(checkout)

    # 4. Rebuild against the new commit, then record it as the Local pin. A
    #    failed build leaves the pin where it was, so a rerun retries the build.
    before = _world_hash(checkout)
    install(checkout, pin=latest)
    if not updates.same("server", current, latest):
        pins.set_local(checkout, "server", latest)
        print(f"== server Local pin -> {latest['ref'][:12]}", file=sys.stderr)

    # 5. New World data does not reach an existing save on its own: offer a
    #    Progress upgrade, never run one unasked.
    after = _world_hash(checkout)
    if before is None or after == before:
        return 0
    if not sys.stdin.isatty():
        print("World data changed; to move your progress into the new world, run:  "
              "daoc progress upgrade", file=sys.stderr)
        return 0
    print(PROGRESS_UPGRADE.format(world=WORLD_DATA), file=sys.stderr)
    if not ask("Run the Progress upgrade now?"):
        print("skipped; run it later with:  daoc progress upgrade", file=sys.stderr)
        return 0
    # No chdir: daoc-progress resolves its own directory.
    proc.run([tool(checkout, "daoc-progress"), "upgrade"], verbose=True)
    print("== Progress upgrade: done", file=sys.stderr)
    return 0
