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
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import files, games, pins, proc, selection, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, ask, say

NO_INSTALL = "no Server install; run daoc server install"

# The World data a build ships: build-release.sh's WorldBuilder writes it to
# <server_dir>/defaults/world.sqlite, and daoc-server.sh copies it into data/
# only on the first start, so an existing save keeps the world it was made with.
WORLD_DATA = Path("defaults") / "world.sqlite"
# The Edition a fresh save starts as, read by daoc-server.sh on first start.
EDITION_FILE = Path("config") / "edition"


def set_edition(checkout: Checkout, edition: str) -> None:
    """Record the Edition the Server install's next fresh save starts as."""
    if edition not in games.EDITIONS:
        raise DaocError(f"no edition {edition!r} (expected one of: {', '.join(games.EDITIONS)})")
    files.atomic_write(checkout.server_dir / EDITION_FILE, edition + "\n")


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "server",
        help="install, run and update the local OpenDAoC server",
        description="Install, run and update the local OpenDAoC server.",
    )
    actions = p.add_subparsers(dest="action", title="actions")
    a = actions.add_parser("install", help="build server/dist/daoc-server for the selected game version")
    a.add_argument("-v", "--verbose", action="store_true",
                   help="show git progress and the build's warnings and tool output")
    a.set_defaults(func=_handle_install)
    a = actions.add_parser(
        "update",
        help="move the server to the fork's latest commit for the selected version and rebuild (Local pin)",
        description="Resolve the fork's latest main commit, check it is synced to the selected "
                    "game version, pre-check the port patches against it, record it as a Local "
                    "pin and rebuild the Server install.",
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
    game = selection.load(checkout).game
    install(checkout, game.version, verbose=args.verbose)
    set_edition(checkout, game.edition)
    return 0


def _handle_update(args: argparse.Namespace, checkout: Checkout) -> int:
    if args.check:
        return updates.check(checkout, "server", _version(checkout))
    return update(checkout)


def _version(checkout: Checkout) -> str:
    """The selected Game's Version."""
    return selection.load(checkout).game.version


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


def install(checkout: Checkout, version: str, verbose: bool = False,
            pin: Optional[Dict[str, Any]] = None) -> None:
    """Build the Server install of game version from pin (default: its effective
    server pin)."""
    # Resolve symlinks: MSBuild must see one path (the old script's `cd "$(pwd -P)"`).
    root = Path(os.path.realpath(checkout.root))
    progress = "--progress" if verbose else "--quiet"
    pin = pin if pin is not None else pins.effective(checkout, "server", version)
    url, ref = pin["upstream"], pin["ref"]
    navmesh_ref = pin.get("navmesh_ref") or ref
    src = root / "upstream" / "server"

    # 1. Fetch the pinned upstream as a git clone, verify the exact commit, and
    #    pre-check the port patches against it (a ref change or an upstream edit
    #    that breaks a patch fails here, loudly, before any build time is spent).
    say(f"install-server: pinned upstream {ref[:12]}")
    (root / "downloads").mkdir(parents=True, exist_ok=True)
    (root / "upstream").mkdir(parents=True, exist_ok=True)
    if src.is_dir() and not (src / ".git").is_dir():
        # Tarball-era extract (pre-git pinning): replace it with a proper clone.
        say("replacing tarball-era upstream extract with a git clone")
        shutil.rmtree(src)
    if not (src / ".git").is_dir():
        say("cloning upstream (this downloads ~400 MB)")
        proc.run(["git", "clone", progress, url, str(src)], verbose=True)
    checked = proc.head(src)
    if checked != ref:
        say(f"checking out pinned {ref[:12]} (have {checked[:12]})")
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
    patches = [str(p) for p in _patches(root, version)]
    if proc.git(src, "apply", "--check", *patches, verbose=True, check=False).returncode != 0:
        raise DaocError("patches no longer apply to the pinned upstream — re-derive them")
    say("patches apply cleanly")

    # 2. Toolchain: the port's own installer is idempotent and always safe to run.
    say(".NET 10 SDK (installed into ~/.dotnet if missing)")
    proc.run([root / "server" / "tools" / "setup-dotnet.sh"], cwd=root, verbose=verbose)
    if shutil.which("cmake") is None:
        raise DaocError("cmake missing (brew install cmake)")

    with tempfile.TemporaryDirectory(prefix="daoc-navmesh-") as navmesh_src:
        _export_navmesh(src, navmesh_ref, ref, Path(navmesh_src), progress, verbose)
        # 3. Build. Pin DAOC_SOURCE_REPO to the clone verified above so the build (and the DB
        #    fetcher it calls) can't pick up a different tree from an inherited environment.
        env = dict(os.environ, DAOC_SOURCE_REPO=str(src), DAOC_GAME_VERSION=version,
                   DAOC_NAVMESH_SRC=navmesh_src)
        build = [str(root / "server" / "tools" / "build-release.sh")]
        if verbose:
            build.append("--verbose")
        # A build that stops halfway leaves an install built from no pin.
        pins.forget_installed(checkout, "server")
        proc.run(build, cwd=root, env=env, verbose=True)
    pins.record_installed(checkout, "server", pin)

    say("install-server: done — server/dist/daoc-server; start it with daoc server start")


NAVMESH_PATHS = ("world/navmesh", "world/navmesh-manifest.sha256")


def _export_navmesh(src: Path, navmesh_ref: str, ref: str, dest: Path, progress: str,
                    verbose: bool) -> None:
    """Write navmesh_ref's world/navmesh/ and its manifest into dest. A Version
    whose own commit has no navmeshes names the commit that has them
    (navmesh_ref); fetch it into the clone first."""
    if navmesh_ref != ref:
        if proc.git(src, "fetch", progress, "origin", navmesh_ref, verbose=verbose,
                    check=False).returncode != 0:
            proc.git(src, "fetch", progress, "origin", verbose=True)
    tar = dest / "navmesh.tar"
    proc.git(src, "archive", f"--output={tar}", navmesh_ref, *NAVMESH_PATHS, verbose=verbose)
    with tarfile.open(tar) as archive:
        base = str(dest.resolve()) + "/"
        for member in archive.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(base) or not (member.isfile() or member.isdir()):
                raise DaocError(f"unexpected entry {member.name!r} in the navmesh export")
        archive.extractall(dest)
    tar.unlink()


def _patches(root: Path, version: str) -> List[Path]:
    """server/patches/<version>/*.patch in the order build-release.sh applies them."""
    folder = root / "server" / "patches" / version
    found = sorted(folder.glob("*.patch"))
    if not found:
        raise DaocError(f"no macOS patches for game version {version} in {folder}")
    return found


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
        say(f"cloning upstream at {ref[:12]} to pre-check the port patches")
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
    say(f"patches apply cleanly to {ref[:12]}")


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
bots, plus this install's settings (population, daoc-admin options, XP rates);
the edition is the selected game's. Realm-wide world state such as keep and relic ownership starts
fresh. The previous save is backed up to data/progress-backups/<time>/."""


def update(checkout: Checkout) -> int:
    """Move the Server install to the upstream's latest main and rebuild it,
    recording that commit as the Local pin unless the pin already names it. Exit 0
    (updated, or the install already built from latest); DaocError 1 on a
    failing patch or build, 2 when stopping the server is refused."""
    root = Path(os.path.realpath(checkout.root))

    # 1. Resolve the upstream's latest main. Whether the install is already there
    #    is read from the install, not the pin: a pull can move the pin alone.
    say("resolving upstream main")
    game = selection.load(checkout).game
    version, edition = game.version, game.edition
    current = pins.effective(checkout, "server", version)
    latest = updates.resolve_latest(checkout, "server", version)
    if pins.built_from(checkout, "server", latest)[1]:
        say(f"server already at {latest['ref'][:12]}")
        # The pin can lag the install: a lapsed Local pin, or a rerun after an
        # update stopped between the build and step 4's set_local.
        if not pins.same("server", current, latest):
            pins.set_local(checkout, "server", latest, version)
            say(f"server Local pin -> {latest['ref'][:12]}")
        return 0

    # 2. Clone the new commit (blobless) and prove the port patches still apply to
    #    it BEFORE moving the pin: an upstream change that breaks a patch fails
    #    here, loudly, and the pin stays put.
    _precheck(latest["upstream"], latest["ref"], _patches(root, version), current["ref"])

    # 3. Never rebuild under a live server.
    _stop_first(checkout)

    # 4. Rebuild against the new commit, then record it as the Local pin. A
    #    failed build leaves the pin where it was, so a rerun retries the build.
    before = _world_hash(checkout)
    install(checkout, version, pin=latest)
    set_edition(checkout, edition)
    if not pins.same("server", current, latest):
        pins.set_local(checkout, "server", latest, version)
        say(f"server Local pin -> {latest['ref'][:12]}")

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
        say("skipped; run it later with:  daoc progress upgrade")
        return 0
    # No chdir: daoc-progress resolves its own directory.
    proc.run([tool(checkout, "daoc-progress"), "upgrade", f"--edition={edition}"], verbose=True)
    say("Progress upgrade: done")
    return 0
