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
update moves the Client install to the latest OfflineDAoC release:
  1. Download and verify it (cached), and hash its game.dll inside the archive:
     a build that is not Proven stops here, before any change.
  2. Refuse while the client runs.
  3. Graphics carry-over through the pinned daoc-gfx: save `status --json` in
     .daoc/carry-over.json, export the texture pack to .daoc/textures-export,
     then turn every graphics patch off.
  4. Replace dist/OfflineDAoC (extracted beside it, then swapped; the Wine
     prefix is kept), apply the Client patch and record the Local pin.
  5. Turn the same patches back on, reinstall the pack from the export, and
     compare `status --json` with the saved one; a difference keeps both files.
A carry-over.json left by an interrupted update resumes at step 5.
Downloads are cached in downloads/. start/stop/kill/login live in
client_runtime.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from daoc_cli import (bench, client_patch, client_runtime, graphics, pins, proc, release,
                      updates)
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

XATTR = "/usr/bin/xattr"
ARCH = "/usr/bin/arch"
TAR = "/usr/bin/tar"

# game.dll below the Client install (and below the release archive's root folder).
GAME_DLL = "runtime/client-opendaoc/app/game.dll"
CARRY_OVER = "carry-over.json"
TEXTURES_EXPORT = "textures-export"
# daoc-gfx patches restored by carry_over's own steps rather than a plain enable.
_NOT_DISPLAY = ("textures", "anisotropy")


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
    return update(checkout)


def _gfx_checked(result: "subprocess.CompletedProcess[str]", args: List[str]) -> str:
    """result's stdout; on failure replay its output and raise."""
    if result.returncode != 0:
        for captured in (result.stdout, result.stderr):
            if captured:
                sys.stderr.write(captured if captured.endswith("\n") else captured + "\n")
        sys.stderr.flush()
        raise DaocError(f"daoc-gfx {' '.join(args)} failed (exit {result.returncode})")
    return result.stdout


def _gfx(checkout: Checkout, *args: str) -> str:
    """daoc-gfx args; on failure replay its output and raise."""
    return _gfx_checked(graphics.gfx(checkout, list(args)), list(args))


def _gfx_status(checkout: Checkout) -> Dict[str, Any]:
    """daoc-gfx `status --json` (schema 1)."""
    args = ["status", "--json"]
    result = graphics.gfx(checkout, args)
    if result.returncode != 0 and "unrecognized arguments" in (result.stderr or ""):
        raise DaocError("the pinned daoc-gfx has no `status --json`, which the graphics "
                        "carry-over needs; run `daoc graphics update` first, then "
                        "`daoc client update` again")
    _gfx_checked(result, args)
    try:
        status = json.loads(result.stdout)
    except ValueError:
        status = None
    if not isinstance(status, dict) or status.get("schema") != graphics.STATUS_SCHEMA:
        raise DaocError(f"the pinned daoc-gfx gave no schema {graphics.STATUS_SCHEMA} "
                        "`status --json`; run `daoc graphics update` first, then "
                        "`daoc client update` again")
    return status


def _refuse_running(checkout: Checkout) -> None:
    if client_runtime.game_pids(checkout):
        raise DaocError("the client is running; quit the game (or `daoc client stop`) and "
                        "run `daoc client update` again", 2)


def carry_over(checkout: Checkout) -> Optional[Dict[str, Any]]:
    """Save the graphics state (.daoc/carry-over.json), export the texture
    pack (.daoc/textures-export) and turn every graphics patch off; return the
    saved state, or None when there is nothing to carry over."""
    if not (checkout.app_dir / "game.dll").is_file():
        _say("no client game.dll yet; skipping the graphics carry-over")
        return None
    if not isinstance(checkout.manifest.get("graphics"), dict):
        _say("no graphics pin in manifest.json; skipping the graphics carry-over")
        return None
    status = _gfx_status(checkout)
    if status["textures"]["pending"]:
        raise DaocError(f"graphics has an interrupted '{status['textures']['pending']}'; "
                        "run `daoc graphics textures recover` first")
    export = checkout.state / TEXTURES_EXPORT
    # Without a carry-over.json no update owns an export, so any one is stale.
    shutil.rmtree(export, ignore_errors=True)
    if status["textures"]["components"]:
        _say(f"graphics: exporting the texture pack to {export}")
        export.parent.mkdir(parents=True, exist_ok=True)
        _gfx(checkout, "textures", "export", str(export))
    # Written once the export is complete: from here on a re-run restores.
    pins.atomic_write(checkout.state / CARRY_OVER, json.dumps(status, indent=2) + "\n")
    active = [p for p, s in status["patches"].items() if s not in ("off", "not installed")]
    if active:
        _say(f"graphics: turning off {', '.join(active)} for the replace")
        _gfx(checkout, "disable", *active)
    return status


def _differences(saved: Dict[str, Any], now: Dict[str, Any]) -> List[str]:
    out = []
    for key in sorted(set(saved) | set(now)):
        was, got = saved.get(key), now.get(key)
        if key == "patches" and isinstance(was, dict) and isinstance(got, dict):
            out += [f"{p}: was {was.get(p, 'absent')}, now {got.get(p, 'absent')}"
                    for p in sorted(set(was) | set(got)) if was.get(p) != got.get(p)]
        elif was != got:
            out.append(f"{key}: was {json.dumps(was)}, now {json.dumps(got)}")
    return out


def restore(checkout: Checkout, saved: Dict[str, Any]) -> None:
    """Bring the graphics state saved by carry_over back on the current client.

    Steps already done (by an interrupted run) are skipped. A remaining
    difference keeps carry-over.json and the export and raises; on success
    both are deleted.
    """
    state, export = checkout.state / CARRY_OVER, checkout.state / TEXTURES_EXPORT
    was = saved["patches"]
    now = _gfx_status(checkout)
    display = [p for p, s in was.items()
               if s == "on" and p not in _NOT_DISPLAY and now["patches"].get(p) != "on"]
    if display:
        _say(f"graphics: turning {', '.join(display)} back on")
        _gfx(checkout, "enable", *display)
    level = saved.get("anisotropy_level")
    if was.get("anisotropy") == "on" and (now["patches"].get("anisotropy") != "on"
                                          or now.get("anisotropy_level") != level):
        _say(f"graphics: turning anisotropy back on ({level}x)")
        _gfx(checkout, "enable", "anisotropy", *(["--level", str(level)] if level else []))
    components = saved["textures"]["components"]
    if components and not now["textures"]["components"]:
        _say("graphics: reinstalling the texture pack from the export")
        _gfx(checkout, "textures", "install", "--from-dir", str(export))
        now = _gfx_status(checkout)
    # A fresh install leaves every component pack-active; a restore on the old
    # client (an update that stopped before the replace) finds them all original.
    live = {c["name"]: c["state"] for c in now["textures"]["components"]}
    for variant, want, other in (("original", "originals active", "pack active"),
                                 ("pack", "pack active", "originals active")):
        names = [c["name"] for c in components
                 if c["state"] == want and live.get(c["name"]) == other]
        if names:
            _gfx(checkout, "textures", "use", variant, *[a for n in names for a in ("-c", n)])
    diff = _differences(saved, _gfx_status(checkout))
    if diff:
        raise DaocError(
            "graphics did not come back as before the update:\n  " + "\n  ".join(diff)
            + f"\nthe saved state is kept in {state}"
            + (f" and the texture pack in {export}" if export.exists() else "")
            + "; set it with `daoc graphics …`, then run `daoc client update` again to "
              "compare (delete those to accept the current state)")
    # carry-over.json first: an export without it is stale, the reverse would resume
    # without its pack.
    state.unlink()
    shutil.rmtree(export, ignore_errors=True)
    _say("graphics: carried over")


def _swap_dirs(checkout: Checkout) -> Tuple[Path, Path]:
    """(staging, old): the folders beside the Client install a replace uses."""
    dist, name = checkout.client_root.parent, checkout.client_root.name
    return dist / f".{name}.new", dist / f".{name}.old"


def _recover_swap(checkout: Checkout) -> None:
    """Finish or undo a replace that was interrupted between its renames."""
    staging, old = _swap_dirs(checkout)
    if old.exists():
        if checkout.client_root.exists():
            shutil.rmtree(old)
        else:
            old.rename(checkout.client_root)
            _say("put back the client an interrupted update had moved aside")
    shutil.rmtree(staging, ignore_errors=True)


def replace_install(checkout: Checkout, archive: Path, root_folder: str) -> None:
    """Replace the Client install with the release in archive, then apply the
    Client patch. The release is extracted beside the install and swapped in,
    so the old install stays whole until the new one is complete."""
    staging, old = _swap_dirs(checkout)
    shutil.rmtree(staging, ignore_errors=True)
    new = release.extract(archive, root_folder, staging)
    if checkout.client_root.exists():
        checkout.client_root.rename(old)
    os.replace(new, checkout.client_root)
    _say("removing the old client")
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(staging)
    client_patch.patch(checkout.app_dir / "game.dll")


def update(checkout: Checkout, fetch_url: Optional[release.Downloader] = None) -> int:
    """Move the Client install to the latest OfflineDAoC release (Local pin),
    carrying the graphics patches over. fetch_url defaults to release.download."""
    _recover_swap(checkout)
    saved_path = checkout.state / CARRY_OVER
    if saved_path.is_file():
        _refuse_running(checkout)
        _say(f"resuming an interrupted client update at the graphics restore ({saved_path})")
        try:
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise DaocError(f"cannot read {saved_path}: {e}") from None
        restore(checkout, saved)

    latest = updates.resolve_latest(checkout, "client")
    current = pins.effective(checkout, "client")
    version = latest["version"]
    if updates.same("client", latest, current):
        _say(f"client already at {version}")
        return 0
    _say(f"client update: OfflineDAoC {current['version']} -> {version}")
    archive = release.download_release(latest, checkout.downloads / f"v{version}",
                                       fetch_url=fetch_url or release.download)
    sha = release.member_sha256(archive, f"{latest['root_folder']}/{GAME_DLL}")
    if sha not in client_patch.PROVEN_BUILDS:
        raise DaocError(f"{version}'s game.dll ({sha[:12]}) is not a Proven build; "
                        "it needs a shipped update")
    _refuse_running(checkout)
    saved = carry_over(checkout)
    replace_install(checkout, archive, latest["root_folder"])
    # The pin follows the install as soon as it is replaced, so a failed restore
    # resumes against the right pin.
    pins.set_local(checkout, "client", dict(latest, game_dll_sha256=sha))
    if saved is not None:
        restore(checkout, saved)
    _say(f"client update: done; OfflineDAoC {version} is the Local client pin "
         "(`daoc dev ship-pins` makes it Shipped)")
    return 0


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


def _install_paths(checkout: Checkout) -> Tuple[Path, Path]:
    """(wine home, prefix) that install builds: always <root>/dist/wine and
    <root>/dist/prefix. DAOC_WINE_HOME / DAOC_WINEPREFIX are runtime overrides
    (launcher, kill, bench) and never install targets: install deletes and
    initializes what it targets."""
    dist = checkout.root / "dist"
    return dist / "wine", dist / "prefix"


def _install_wine(checkout: Checkout, verbose: bool) -> None:
    wine_home, _ = _install_paths(checkout)
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
    # The tarball's root is wine/; strip it so the bundle lands directly in dist/wine.
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
    wine_home, prefix = _install_paths(checkout)  # absolute: wine rejects a relative WINEPREFIX
    wine = str(wine_home / "bin" / "wine")
    wineserver = str(wine_home / "bin" / "wineserver")
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
