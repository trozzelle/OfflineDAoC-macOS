"""`daoc client`: install the OfflineDAoC client under Wine on macOS.

install, in order (re-runs skip finished steps):
  1. Requirements: macOS, and Rosetta 2 on Apple Silicon.
  2. Wine: fetch and verify athei/wine-build (manifest.json `wine`): CrossOver
     Wine with the x87sidecar Rosetta x87 JIT and mtld3d (D3D9 on Metal).
  3. Release: fetch, verify, join and extract the pinned OfflineDAoC release
     (see release). Skipped whenever the Client install exists.
  4. Client patch on game.dll (see client_patch).
  5. Wine prefix (win10 version setting, profile folders kept inside the
     prefix, settings carried over from an older wine's user, prefix upgrade)
     and the Launcher bundle.
Downloads are cached in downloads/. start/stop/kill/login live in
client_runtime.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Mapping

from daoc_cli import bench, client_patch, client_runtime, pins, proc, release, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

XATTR = "/usr/bin/xattr"
ARCH = "/usr/bin/arch"
TAR = "/usr/bin/tar"


def _say(msg: str) -> None:
    print(f"daoc: {msg}", file=sys.stderr, flush=True)


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "client",
        help="install, launch and update the game client",
        description="Install, launch and update the OfflineDAoC game client.",
    )
    actions = p.add_subparsers(dest="action", title="actions")
    a = actions.add_parser(
        "install",
        help="install Wine, the OfflineDAoC client, the Client patch and the Wine prefix",
        description="Install Wine, the pinned OfflineDAoC release, the Client patch, the "
                    "Wine prefix and the Launcher. Re-runs skip finished steps.",
    )
    a.add_argument("-v", "--verbose", action="store_true",
                   help="show download progress and Wine's prefix setup logging "
                        "(default: errors only)")
    a.set_defaults(func=_install)
    a = actions.add_parser(
        "update",
        help="move the client to the latest OfflineDAoC release (Local pin)",
        description="Move the Client install to the latest OfflineDAoC release, recorded "
                    "as a Local pin. --check reports without changing anything.",
    )
    a.add_argument("--check", action="store_true",
                   help="report Shipped, Local, built-from and latest; change nothing")
    a.set_defaults(func=_update)
    client_runtime.register(actions)
    bench.register(actions)


def _install(args: argparse.Namespace, checkout: Checkout) -> int:
    install(checkout, verbose=args.verbose)
    return 0


def _update(args: argparse.Namespace, checkout: Checkout) -> int:
    if args.check:
        return updates.check(checkout, "client")
    raise DaocError("client update is not available yet", 2)


def _wine(argv: List[str], env: Mapping[str, str], verbose: bool, check: bool = True) -> None:
    """Run a noisy Wine tool silently; on failure, replay its full output.

    The output goes to a file, not a pipe: wineboot leaves wineserver running
    with the pipe inherited, so reading a pipe to EOF would wait for wineserver.
    """
    if verbose:
        proc.run(argv, env=env, verbose=True, check=check)
        return
    name = Path(argv[0]).name
    with tempfile.TemporaryFile() as log:
        try:
            rc = subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        except OSError as e:
            raise DaocError(f"cannot run {argv[0]}: {e.strerror or e}") from None
        if rc == 0 or not check:
            return
        log.seek(0)
        sys.stderr.write(log.read().decode("utf-8", "replace"))
        sys.stderr.flush()
    if rc < 0:
        raise DaocError(f"{name} {argv[1]} was killed by signal {-rc}")
    raise DaocError(f"{name} {argv[1]} failed (exit {rc})")


def _unquarantine(path: Path) -> None:
    """Gatekeeper quarantine must not block the bundle's binaries."""
    try:
        proc.run([XATTR, "-dr", "com.apple.quarantine", path], check=False)
    except DaocError:
        pass


def _requirements() -> None:
    if platform.system() != "Darwin":
        raise DaocError("macOS required")
    if platform.machine() == "arm64":
        # The Wine build is x86_64; Apple Silicon needs Rosetta 2. A functional
        # probe (can we execute an x86_64 binary?) beats checking for the oahd
        # daemon, whose process name varies across macOS versions.
        if proc.run([ARCH, "-x86_64", "/usr/bin/true"], check=False).returncode != 0:
            raise DaocError("Rosetta 2 not installed "
                            "(softwareupdate --install-rosetta --agree-to-license)")
    # The wine bundle carries its own libraries (no GStreamer needed): audio
    # goes through winecoreaudio.
    if shutil.which("curl") is None:
        raise DaocError("curl required")


def _install_wine(checkout: Checkout, verbose: bool) -> None:
    wine_home = checkout.wine_home
    if os.access(wine_home / "bin" / "wine", os.X_OK):
        _say("wine already installed")
        return
    pin = checkout.manifest["wine"]
    tarball = checkout.downloads / pin["tarball"]
    if not tarball.is_file():
        _say(f"downloading Wine ({pin['tarball']})")
        proc.run(["curl", "-fSL", "-#" if verbose else "-s", "--retry", "3", pin["url"],
                  "-o", tarball], verbose=verbose)
    actual = release.sha256_file(tarball)
    if actual != pin["sha256"]:
        raise DaocError(f"wine tarball checksum mismatch\n  expected {pin['sha256']}\n"
                        f"  actual   {actual}")
    _say("extracting Wine")
    shutil.rmtree(wine_home, ignore_errors=True)
    wine_home.mkdir(parents=True)
    # The tarball's root is wine/; strip it so DAOC_WINE_HOME may name any folder.
    proc.run([TAR, "-xJf", tarball, "-C", wine_home, "--strip-components", "1"])
    _unquarantine(wine_home)


def _install_release(checkout: Checkout) -> None:
    if checkout.client_root.is_dir():
        _say("OfflineDAoC already installed")
        return
    version = pins.effective(checkout, "client")["version"]
    _say(f"fetching OfflineDAoC v{version} (this is a ~5 GB download)")
    release.install(checkout)


def _patch_client(checkout: Checkout) -> None:
    if (checkout.app_dir / "game.dll.orig").is_file():
        _say("client already patched")
        return
    client_patch.patch(checkout.app_dir / "game.dll")


def _keep_profile_folders(users: Path) -> None:
    """Wine links the Windows profile folders (Documents, Desktop, ...) of every
    prefix user (this wine's is "crossover") to the macOS home folders. The first
    touch of ~/Documents raises a TCC prompt for the wine binary and the client
    blocks until it is answered, so keep those folders inside the prefix: every
    symlink up to 3 levels below drive_c/users becomes an empty folder."""
    links = []
    for top, dirs, files in os.walk(users):
        depth = len(Path(top).relative_to(users).parts) + 1
        links += [Path(top) / n for n in dirs + files if (Path(top) / n).is_symlink()]
        if depth >= 3:
            dirs[:] = []
    for link in links:
        link.unlink()
        link.mkdir(parents=True, exist_ok=True)


def _init_prefix(checkout: Checkout, verbose: bool) -> None:
    prefix = checkout.prefix  # absolute: wine rejects a relative WINEPREFIX
    wine = str(checkout.wine_home / "bin" / "wine")
    wineserver = str(checkout.wine_home / "bin" / "wineserver")
    env = dict(os.environ, WINEPREFIX=str(prefix))
    if not (prefix / "system.reg").is_file():
        _say("initializing wine prefix (win10 version)")
        _wine([wine, "wineboot", "-i"], env, verbose)
        _wine([wine, "reg", "add", "HKCU\\Software\\Wine", "/v", "Version", "/d", "win10", "/f"],
              env, verbose, check=False)
        # Wait for wineserver to flush the registry hives before checking them.
        _wine([wineserver, "-w"], env, verbose)
        if not (prefix / "system.reg").is_file():
            raise DaocError("wine prefix init failed")
    else:
        _say("wine prefix already initialized")
    # Bring an existing prefix (e.g. one made by an older wine) up to this
    # wine's version now, so its first game launch does not do it.
    _wine([wine, "wineboot", "-u"], env, verbose)
    _wine([wineserver, "-w"], env, verbose)

    users = prefix / "drive_c" / "users"
    if users.is_dir():
        _keep_profile_folders(users)
    # Settings from a prefix made by another wine (e.g. Wine Staging), whose
    # Windows user is the macOS user name: carry them over to this wine's
    # "crossover" user unless it already has its own.
    user = os.environ.get("USER", "")
    ea = Path("AppData") / "Roaming" / "Electronic Arts"
    ea_old, ea_new = users / user / ea, users / "crossover" / ea
    if user and user != "crossover" and ea_old.is_dir() and not os.path.lexists(ea_new):
        _say(f"copying client settings from prefix user {user} to crossover")
        ea_new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ea_old, ea_new, symlinks=True)


def _install_launcher(checkout: Checkout) -> None:
    """The Launcher bundle resolves paths relative to its own location, so it
    is copied next to the Client install."""
    dst = checkout.launcher_app
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(checkout.root / "client" / "DAoCLauncher.app", dst, symlinks=True)
    _unquarantine(dst)


def install(checkout: Checkout, verbose: bool = False) -> None:
    """Install or complete the Client install; finished steps are skipped."""
    version = pins.effective(checkout, "client")["version"]
    _say(f"client install: OfflineDAoC v{version} + CrossOver Wine (x87sidecar)")
    _requirements()
    checkout.downloads.mkdir(parents=True, exist_ok=True)
    checkout.client_root.parent.mkdir(parents=True, exist_ok=True)
    _install_wine(checkout, verbose)
    _install_release(checkout)
    _patch_client(checkout)
    _init_prefix(checkout, verbose)
    _install_launcher(checkout)
    _say("client install: done; launch the game (server running) with: daoc client start")
