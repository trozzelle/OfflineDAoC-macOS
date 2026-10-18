"""`daoc client`: install the OfflineDAoC client under Wine on macOS.

install, in order, with the flavour's Wine (--wine rosetta | arm64; re-runs skip
finished steps, except the Client patch, the prefix upgrade and the Launcher
copy, which always run):
  1. Requirements: the macOS the flavour's Wine pin needs (manifest.json
     `min_macos`); Apple Silicon for the arm64 Wine, Rosetta 2 on Apple
     Silicon for the rosetta Wine.
  2. Wine: rosetta fetches and verifies athei/wine-build (manifest.json
     `wine`): CrossOver Wine with the x87sidecar Rosetta x87 JIT and mtld3d
     (D3D9 on Metal). arm64 fetches and verifies Hadron's disk image
     (manifest.json `wine_arm64`) and copies its arm64 Wine with FEX out
     unchanged; a new pin replaces it. Then the flavour's mtld3d choice
     (.daoc/mtld3d.json, default fork; see mtld3d and client mtld3d): fork
     fetches our mtld3d build (manifest.json `mtld3d`) and swaps it in, the
     Wine's own files saved in the Wine tree; stock puts those back.
  3. Release: fetch, verify, join and extract the selected Game Version's
     OfflineDAoC release (see release) beside the install, then swap it in, as
     update does: an interrupted extraction leaves nothing in the way of a
     re-run. An existing Client install built from another release (the pin it
     records, see pins.INSTALLED) is replaced, graphics carried over; one built
     from the pin is kept. Then the Game's Edition: its game.dll from the
     install's editions/ folder (Classic classes) or the cached release
     (Sluaghbinder), swapped in without a re-extract (apply_edition).
  4. Client patch on game.dll (see client_patch); a no-op when current.
  5. The flavour's Wine prefix (win10 version setting, prefix upgrade, profile
     folders kept inside the prefix, settings carried over from another user
     or the other flavour's prefix, client sound off unless its settings say
     otherwise); for arm64 also the Wine's mtld3d as d3d9 and a check that
     macOS is not holding Wine's Local Network access.
  6. The Launcher bundle, then the flavour record: daoc client start uses
     this Wine only after a complete install.
update moves the Client install to the latest OfflineDAoC release:
  1. Download and verify it (cached), and hash its game.dll inside the archive:
     a build that is not Proven stops here, before any change.
  2. Refuse while the client runs.
  3. Graphics carry-over through the pinned daoc-gfx: save `status --json` in
     .daoc/carry-over.json, export the texture pack to .daoc/textures-export,
     then turn every graphics patch off.
  4. Replace dist/OfflineDAoC (extracted beside it, then swapped; the Wine
     prefix is kept), apply the Client patch, record the pin in the install and
     record the Local pin.
  5. Turn the same patches back on, reinstall the pack from the export, and
     compare `status --json` with the saved one; a difference keeps both files.
A carry-over.json left by an interrupted install or update resumes at step 5.
Downloads are cached in downloads/. start/stop/kill/login live in
client_runtime.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from daoc_cli import (bench, client_patch, client_runtime, games, graphics, mtld3d, newclient,
                      pins, proc, release, selection, updates)
from daoc_cli.checkout import FLAVOURS, Checkout, wine_env, wine_is_arm64
from daoc_cli.errors import DaocError, say
from daoc_cli.files import atomic_write, sha256
from daoc_cli.games import Game

XATTR = "/usr/bin/xattr"
ARCH = "/usr/bin/arch"
SW_VERS = "/usr/bin/sw_vers"
TAR = "/usr/bin/tar"
DISKUTIL = "/usr/sbin/diskutil"
DITTO = "/usr/bin/ditto"
# The arm64 Wine's record of the disk image it was copied from (reinstall on a new pin).
WINE_RECORD = ".daoc-wine.json"
# Wine's warning when it cannot resolve the Mac's own name, which the arm64 Wine
# hits while macOS holds its Local Network access (prompt unanswered or denied).
LOCAL_NETWORK_MISS = "Failed to resolve your host name IP"

# game.dll below the Client install (and below the release archive's root folder).
GAME_DLL = "runtime/client-opendaoc/app/game.dll"
CARRY_OVER = "carry-over.json"
TEXTURES_EXPORT = "textures-export"
# daoc-gfx patches restored by carry_over's own steps rather than a plain enable.
_NOT_DISPLAY = ("textures", "anisotropy")


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "client",
        help="install, launch and update the game client",
        description="Install, launch and update the OfflineDAoC game client.",
    )
    actions = p.add_subparsers(dest="action", title="actions")
    a = actions.add_parser(
        "install",
        help="install the selected game's client and make it the default",
        description="Install the selected game's client. The original client: Wine, the "
                    "pinned OfflineDAoC release with the game's edition, the Client patch, the "
                    "Wine prefix and the Launcher. The new client (0.36 and later): the pinned "
                    "macOS Godot and upstream's client project. Re-runs skip finished steps.",
    )
    a.add_argument("--wine", choices=FLAVOURS, default=None,
                   help="Wine to install and use: rosetta (x86_64 CrossOver Wine under "
                        "Rosetta 2, the default) or arm64 (Hadron's arm64 Wine with FEX, no "
                        "Rosetta; macOS 27+). Both can be installed; the last one installed "
                        "is the one daoc client start uses. Default: the current one.")
    a.add_argument("--client", choices=games.CLIENTS, default=None,
                   help="client to install and start by default: original (the 1.127 Windows "
                        "client under Wine) or new (upstream's Godot client, from 0.36; about "
                        "34 GB). Both can be installed. Default: the current default client.")
    a.add_argument("-v", "--verbose", action="store_true",
                   help="show download progress and Wine's prefix setup logging "
                        "(default: errors only)")
    a.set_defaults(func=_install)
    a = actions.add_parser(
        "update",
        help="take the default client's release again if upstream replaced its files (Local pin)",
        description="Re-read the selected game version's release for the default client and "
                    "move that client to it when upstream replaced its files, recorded as a "
                    "Local pin. --check reports the default client's pin without changing "
                    "anything, and names a newer upstream version.",
    )
    a.add_argument("--check", action="store_true",
                   help="report Shipped, Local, built-from and latest; change nothing")
    a.set_defaults(func=_update)
    a = actions.add_parser(
        "mtld3d",
        help="use our mtld3d build (fork) or the Wine's own (stock)",
        description="Put our mtld3d fork build (manifest.json `mtld3d`) into the Wine, or "
                    "put the Wine's own mtld3d back; with no argument, print which one it "
                    "has. The choice is kept per Wine in .daoc/mtld3d.json, so client "
                    "install (also of a new Wine) keeps it.",
    )
    a.add_argument("choice", nargs="?", choices=mtld3d.CHOICES,
                   help="fork: our build (the default); stock: the Wine's own")
    a.add_argument("--wine", choices=FLAVOURS, default=None,
                   help="the Wine to change (default: the current one)")
    a.set_defaults(func=_mtld3d)
    client_runtime.register(actions)
    bench.register(actions)


def _install(args: argparse.Namespace, checkout: Checkout) -> int:
    sel = selection.load(checkout)
    which = args.client or sel.client
    if which == "new":
        if args.wine:
            raise DaocError("--wine applies to the original client", 2)
        newclient.install(checkout, sel.game)
    else:
        install(checkout, flavour=args.wine, verbose=args.verbose)
    if which != sel.client:
        selection.save(checkout, sel._replace(client=which))
        say(f"daoc client start now starts the {which} client "
            f"(switch back with: daoc client install --client {sel.client})")
    return 0


def _update(args: argparse.Namespace, checkout: Checkout) -> int:
    if args.check:
        sel = selection.load(checkout)
        group = "new_client" if sel.client == "new" else "original_client"
        return updates.check(checkout, group, sel.game.version)
    return update(checkout)


def _mtld3d(args: argparse.Namespace, checkout: Checkout) -> int:
    flavour = args.wine or checkout.flavour
    wine_home, prefix = checkout.flavour_paths(flavour)
    if not (wine_home / "bin" / "wine").is_file():
        raise DaocError(f"the {flavour} Wine is not installed; run: "
                        f"daoc client install --wine {flavour}")
    if args.choice is None:
        print(mtld3d.state(wine_home, flavour))
        return 0
    _refuse_running(checkout, "mtld3d", wine_home)
    if args.choice == "fork":
        mtld3d.apply(wine_home, flavour, mtld3d.fetch_bundle(checkout),
                     checkout.manifest["mtld3d"]["version"])
    else:
        mtld3d.restore_stock(wine_home, flavour)
    mtld3d.set_choice(checkout, flavour, args.choice)
    if wine_is_arm64(wine_home) and (prefix / "system.reg").is_file():
        _install_mtld3d(wine_home, prefix)
    return 0


def _apply_mtld3d_choice(checkout: Checkout, flavour: str) -> None:
    """Give the flavour's Wine the recorded mtld3d (default: the fork build).
    When that changes an arm64 Wine whose prefix exists, the prefix copies
    follow at once, so an install interrupted before the prefix step never
    leaves the prefix's d3d9.dll paired with another mtld3d.dll/.so."""
    wine_home, prefix = checkout.flavour_paths(flavour)
    current = mtld3d.state(wine_home, flavour)
    if mtld3d.choice(checkout, flavour) == "stock":
        if current == "stock":
            return
        mtld3d.restore_stock(wine_home, flavour)
    else:
        version = checkout.manifest["mtld3d"]["version"]
        if current == f"fork {version}":
            say(f"mtld3d {version} already installed")
            return
        mtld3d.apply(wine_home, flavour, mtld3d.fetch_bundle(checkout), version)
    if wine_is_arm64(wine_home) and (prefix / "system.reg").is_file():
        _install_mtld3d(wine_home, prefix)
def _version(checkout: Checkout) -> str:
    """The selected Game's Version."""
    return selection.load(checkout).game.version


def _gfx_checked(result: "subprocess.CompletedProcess[str]", args: List[str]) -> str:
    """result's stdout; on failure replay its output and raise."""
    if result.returncode != 0:
        proc.replay(result.stdout, result.stderr)
        raise proc.failed(f"daoc-gfx {' '.join(args)}", result.returncode)
    return result.stdout


def _gfx(checkout: Checkout, *args: str) -> str:
    """daoc-gfx args; on failure replay its output and raise."""
    return _gfx_checked(graphics.gfx(checkout, list(args)), list(args))


def _gfx_status(checkout: Checkout, command: str) -> Dict[str, Any]:
    """daoc-gfx `status --json` (schema 1)."""
    args = ["status", "--json"]
    result = graphics.gfx(checkout, args)
    if result.returncode != 0 and "unrecognized arguments" in (result.stderr or ""):
        raise DaocError("the pinned daoc-gfx has no `status --json`, which the graphics "
                        "carry-over needs; run `daoc graphics update` first, then "
                        f"`daoc client {command}` again")
    _gfx_checked(result, args)
    try:
        status = json.loads(result.stdout)
    except ValueError:
        status = None
    if not isinstance(status, dict) or status.get("schema") != graphics.STATUS_SCHEMA:
        raise DaocError(f"the pinned daoc-gfx gave no schema {graphics.STATUS_SCHEMA} "
                        "`status --json`; run `daoc graphics update` first, then "
                        f"`daoc client {command}` again")
    return status


def _refuse_running(checkout: Checkout, command: str, wine_home: Optional[Path] = None) -> None:
    if client_runtime.game_pids(checkout, wine_home):
        raise DaocError("the client is running; quit the game (or `daoc client stop`) and "
                        f"run `daoc client {command}` again", 2)


def carry_over(checkout: Checkout, command: str) -> Optional[Dict[str, Any]]:
    """Save the graphics state (.daoc/carry-over.json), export the texture
    pack (.daoc/textures-export) and turn every graphics patch off; return the
    saved state, or None when there is nothing to carry over."""
    if not (checkout.app_dir / "game.dll").is_file():
        say("no client game.dll yet; skipping the graphics carry-over")
        return None
    if not isinstance(checkout.manifest.get("graphics"), dict):
        say("no graphics pin in manifest.json; skipping the graphics carry-over")
        return None
    if not (checkout.graphics_src / ".git").is_dir():
        # Only daoc graphics clones it, so no clone means no patch to carry over.
        say(f"no graphics checkout in {checkout.graphics_src}; skipping the graphics carry-over")
        return None
    status = _gfx_status(checkout, command)
    if status["textures"]["pending"]:
        raise DaocError(f"graphics has an interrupted '{status['textures']['pending']}'; "
                        "run `daoc graphics textures recover` first")
    # restore can only bring back what `enable` sets, so a half-applied patch
    # would be lost; textures are carried per component instead.
    partly = [p for p, s in status["patches"].items() if s == "partly on" and p != "textures"]
    if partly:
        names = " ".join(partly)
        raise DaocError(f"graphics patch {names} is partly on, which an update cannot carry "
                        f"over; finish it (`daoc graphics enable {names}`) or turn it off "
                        f"(`daoc graphics disable {names}`), then run `daoc client {command}` "
                        "again", 2)
    if status["mtld3d_conf"] == "your own":
        raise DaocError(f"{checkout.app_dir / 'mtld3d.conf'} is your own file and the update "
                        "replaces that folder; move it aside first, then run "
                        f"`daoc client {command}` again", 2)
    export = checkout.state / TEXTURES_EXPORT
    # Without a carry-over.json no update owns an export, so any one is stale.
    shutil.rmtree(export, ignore_errors=True)
    if status["textures"]["components"]:
        say(f"graphics: exporting the texture pack to {export}")
        export.parent.mkdir(parents=True, exist_ok=True)
        _gfx(checkout, "textures", "export", str(export))
    # Written once the export is complete: from here on a re-run restores.
    atomic_write(checkout.state / CARRY_OVER, json.dumps(status, indent=2) + "\n")
    active = [p for p, s in status["patches"].items() if s not in ("off", "not installed")]
    if active:
        say(f"graphics: turning off {', '.join(active)} for the replace")
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


def restore(checkout: Checkout, saved: Dict[str, Any], command: str) -> None:
    """Bring the graphics state saved by carry_over back on the current client.

    Steps already done (by an interrupted run) are skipped. A remaining
    difference keeps carry-over.json and the export and raises; on success
    both are deleted.
    """
    state, export = checkout.state / CARRY_OVER, checkout.state / TEXTURES_EXPORT
    was = saved["patches"]
    now = _gfx_status(checkout, command)
    display = [p for p, s in was.items()
               if s == "on" and p not in _NOT_DISPLAY and now["patches"].get(p) != "on"]
    if display:
        say(f"graphics: turning {', '.join(display)} back on")
        _gfx(checkout, "enable", *display)
    level = saved.get("anisotropy_level")
    if was.get("anisotropy") == "on" and (now["patches"].get("anisotropy") != "on"
                                          or now.get("anisotropy_level") != level):
        say(f"graphics: turning anisotropy back on ({level}x)")
        _gfx(checkout, "enable", "anisotropy", *(["--level", str(level)] if level else []))
    components = saved["textures"]["components"]
    if components and not now["textures"]["components"]:
        say("graphics: reinstalling the texture pack from the export")
        _gfx(checkout, "textures", "install", "--from-dir", str(export))
        now = _gfx_status(checkout, command)
    # A fresh install leaves every component pack-active; a restore on the old
    # client (an update that stopped before the replace) finds them all original.
    live = {c["name"]: c["state"] for c in now["textures"]["components"]}
    for variant, want, other in (("original", "originals active", "pack active"),
                                 ("pack", "pack active", "originals active")):
        names = [c["name"] for c in components
                 if c["state"] == want and live.get(c["name"]) == other]
        if names:
            _gfx(checkout, "textures", "use", variant, *[a for n in names for a in ("-c", n)])
    diff = _differences(saved, _gfx_status(checkout, command))
    if diff:
        raise DaocError(
            "graphics did not come back as before the update:\n  " + "\n  ".join(diff)
            + f"\nthe saved state is kept in {state}"
            + (f" and the texture pack in {export}" if export.exists() else "")
            + f"; set it with `daoc graphics …`, then run `daoc client {command}` again to "
              "compare (delete those to accept the current state)")
    # carry-over.json first: an export without it is stale, the reverse would resume
    # without its pack.
    state.unlink()
    shutil.rmtree(export, ignore_errors=True)
    say("graphics: carried over")


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
            say("put back the client an interrupted update had moved aside")
    shutil.rmtree(staging, ignore_errors=True)


def replace_install(checkout: Checkout, archive: Path, pin: Dict[str, Any], local: bool,
                    version: str) -> None:
    """Replace the Client install with pin's release in archive, apply the
    Client patch and record pin in the install; local also makes pin the Local
    original_client pin of version. The release is extracted, patched and
    recorded beside the install, and the pin set, before it is swapped in: an
    interruption leaves either the old install or the finished new one under its pin."""
    staging, old = _swap_dirs(checkout)
    shutil.rmtree(staging, ignore_errors=True)
    new = release.extract(archive, pin["root_folder"], staging)
    client_patch.patch(new / GAME_DLL)
    pins.record_installed(checkout, "original_client", pin, install=new)
    if local:
        pins.set_local(checkout, "original_client", pin, version)
    if checkout.client_root.exists():
        checkout.client_root.rename(old)
    os.replace(new, checkout.client_root)
    say("removing the old client")
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(staging)


def _resume(checkout: Checkout, command: str) -> None:
    """Finish a replace an earlier install or update left unfinished."""
    _recover_swap(checkout)
    saved_path = checkout.state / CARRY_OVER
    if saved_path.is_file():
        _refuse_running(checkout, command)
        say(f"resuming an interrupted client update at the graphics restore ({saved_path})")
        try:
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise DaocError(f"cannot read {saved_path}: {e}") from None
        restore(checkout, saved, command)


def _replace(checkout: Checkout, pin: Dict[str, Any], fetch_url: release.Downloader,
             command: str, version: str, local: bool = False) -> Optional[Dict[str, Any]]:
    """Replace the Client install with pin's release (see replace_install),
    carrying the graphics patches over up to the restore; return the saved
    graphics state for restore, or None."""
    release_version = pin["version"]
    archive = release.download_release(pin, checkout.downloads / f"v{release_version}",
                                       fetch_url=fetch_url)
    sha = release.member_sha256(archive, f"{pin['root_folder']}/{GAME_DLL}")
    if sha not in client_patch.PROVEN_BUILDS:
        raise DaocError(f"{release_version}'s game.dll ({sha[:12]}) is not a Proven build; "
                        "it needs a shipped update")
    _refuse_running(checkout, command)
    saved = carry_over(checkout, command)
    edition = next((e for e, v in (pin.get("editions") or {}).items()
                    if v.get("game_dll_sha256") == sha), None)
    record = dict(pin, game_dll_sha256=sha, **({"edition": edition} if edition else {}))
    replace_install(checkout, archive, record, local, version)
    return saved


def update(checkout: Checkout, fetch_url: Optional[release.Downloader] = None) -> int:
    """Move the Default client to its latest release: the Original client to the latest
    OfflineDAoC release (Local pin), carrying the graphics patches over; the New client
    to its release's latest assets. fetch_url defaults to release.download."""
    sel = selection.load(checkout)
    if sel.client == "new":
        if client_runtime.running_client(checkout) == "new":
            raise DaocError("the new client is running; stop it first: daoc client stop", 2)
        newclient.update(checkout, sel.game, fetch_url)
        return 0
    _resume(checkout, "update")
    game_version = sel.game.version
    latest = updates.resolve_latest(checkout, "original_client", game_version)
    current = pins.effective(checkout, "original_client", game_version)
    version = latest["version"]
    # Read from the install, not the pin: a pull can move the pin alone.
    built, matches = pins.built_from(checkout, "original_client", latest)
    if matches:
        say(f"client already at {version}")
        # The pin can lag the install (a lapsed Local pin); a lapsed pin also
        # drops latest's game.dll hash, so take it from the install's record.
        if not pins.same("original_client", current, latest):
            record = pins.installed(checkout, "original_client") or {}
            pins.set_local(checkout, "original_client", dict(
                latest, game_dll_sha256=record.get("game_dll_sha256")
                or latest.get("game_dll_sha256")), game_version)
            say(f"OfflineDAoC {version} is the Local client pin "
                "(`daoc dev ship-pins` makes it Shipped)")
        return 0
    say(f"client update: OfflineDAoC {built} -> {version}")
    # The pin is set with the replace, so a failed restore resumes against the
    # right pin.
    local = not pins.same("original_client", current, latest)
    saved = _replace(checkout, latest, fetch_url or release.download, "update", game_version, local)
    if saved is not None:
        restore(checkout, saved, "update")
    apply_edition(checkout, selection.load(checkout).game, fetch_url or release.download)
    say(f"client update: done; OfflineDAoC {version} is the Local client pin "
         "(`daoc dev ship-pins` makes it Shipped)" if local else
         f"client update: done; OfflineDAoC {version}")
    return 0


def _wine_output(argv: List[str], env: Mapping[str, str]) -> Tuple[int, str]:
    """Run a Wine tool with its output in a file, not a pipe: wineboot leaves
    wineserver running with the pipe inherited, so reading a pipe to EOF would
    wait for wineserver."""
    with tempfile.TemporaryFile() as log:
        try:
            rc = subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
        except OSError as e:
            raise DaocError(f"cannot run {argv[0]}: {e.strerror or e}") from None
        log.seek(0)
        return rc, log.read().decode("utf-8", "replace")


def _wine(argv: List[str], env: Mapping[str, str], verbose: bool, check: bool = True) -> None:
    """Run a noisy Wine tool silently; on failure, replay its full output."""
    if verbose:
        proc.run(argv, env=env, verbose=True, check=check)
        return
    rc, output = _wine_output(argv, env)
    if rc == 0 or not check:
        return
    proc.replay(output)
    raise proc.failed(f"{Path(argv[0]).name} {argv[1]}", rc)


def _unquarantine(path: Path) -> None:
    """Gatekeeper quarantine must not block the bundle's binaries."""
    try:
        proc.run([XATTR, "-dr", "com.apple.quarantine", path], check=False)
    except DaocError:
        pass


def _macos_version(text: str, source: str) -> Tuple[int, ...]:
    """'26' / '26.0' / '26.4.1' as (major, minor, patch), so '26' == '26.0'."""
    try:
        parts = [int(part) for part in text.split(".")]
    except ValueError:
        raise DaocError(f"cannot read the macOS version ({source} said {text!r})") from None
    return tuple(parts + [0] * (3 - len(parts)))


def _requirements(checkout: Checkout, flavour: str) -> None:
    if platform.system() != "Darwin":
        raise DaocError("macOS required")
    if flavour == "arm64" and platform.machine() != "arm64":
        raise DaocError("--wine arm64 needs a Mac with Apple Silicon")
    # sw_vers, not platform.mac_ver(): a Python linked against an older SDK may
    # be shown a compatibility version.
    running = proc.run([SW_VERS, "-productVersion"]).stdout.strip()
    pin = "wine_arm64" if flavour == "arm64" else "wine"
    minimum = checkout.manifest[pin]["min_macos"]
    if (_macos_version(running, "sw_vers")
            < _macos_version(minimum, f"manifest.json {pin}.min_macos")):
        raise DaocError(f"macOS {minimum} or later required (this Mac runs {running}): "
                        "the pinned Wine build needs it")
    if flavour == "rosetta" and platform.machine() == "arm64":
        # The rosetta Wine build is x86_64; Apple Silicon needs Rosetta 2. A
        # functional probe (can we execute an x86_64 binary?) beats checking for
        # the oahd daemon, whose process name varies across macOS versions.
        if proc.run([ARCH, "-x86_64", "/usr/bin/true"], check=False).returncode != 0:
            raise DaocError("Rosetta 2 not installed "
                            "(softwareupdate --install-rosetta --agree-to-license), "
                            "or install the arm64 Wine instead: daoc client install --wine arm64")
    # Both wine bundles carry their own libraries (no GStreamer needed): audio
    # goes through winecoreaudio.
    if shutil.which("curl") is None:
        raise DaocError("curl required")


def _download(checkout: Checkout, url: str, name: str, sha: str, what: str,
              verbose: bool) -> Path:
    """downloads/<name>, fetched when missing, verified against sha."""
    path = checkout.downloads / name
    if not path.is_file():
        say(f"downloading {what} ({name})")
        proc.run(["curl", "-fSL", "-#" if verbose else "-s", "--retry", "3", url,
                  "-o", path], verbose=verbose)
    actual = sha256(path)
    if actual != sha:
        raise DaocError(f"{name} checksum mismatch\n  expected {sha}\n  actual   {actual}")
    return path


def _install_wine(checkout: Checkout, flavour: str, verbose: bool) -> None:
    """Install the flavour's Wine into its dist/ directory. Install paths are
    never DAOC_WINE_HOME / DAOC_WINEPREFIX: those are runtime overrides
    (launcher, kill, bench), and install deletes and initializes its targets."""
    if flavour == "arm64":
        _install_wine_arm64(checkout, verbose)
        return
    wine_home, _ = checkout.flavour_paths(flavour)
    if os.access(wine_home / "bin" / "wine", os.X_OK):
        say("wine already installed")
        return
    pin = checkout.manifest["wine"]
    tarball = _download(checkout, pin["url"], pin["tarball"], pin["sha256"], "Wine", verbose)
    say("extracting Wine")
    shutil.rmtree(wine_home, ignore_errors=True)
    wine_home.mkdir(parents=True)
    # The tarball's root is wine/; strip it so the bundle lands directly in dist/wine.
    proc.run([TAR, "-xJf", tarball, "-C", wine_home, "--strip-components", "1"])
    _unquarantine(wine_home)


@contextmanager
def _attached(image: Path) -> Iterator[Path]:
    """image attached read-only at a fresh temporary mount point."""
    mount = Path(tempfile.mkdtemp(prefix="daoc-dmg."))
    try:
        proc.run([DISKUTIL, "image", "attach", "--readOnly", "--nobrowse",
                  "--mountPoint", mount, image])
        try:
            yield mount
        finally:
            ejected = proc.run([DISKUTIL, "eject", mount], check=False)
            if ejected.returncode != 0:
                proc.replay(ejected.stdout, ejected.stderr)
                say(f"could not eject {image.name}; it is still attached at {mount} "
                    f"(eject it with: diskutil eject {mount})")
    finally:
        with suppress(OSError):
            mount.rmdir()


def _install_wine_arm64(checkout: Checkout, verbose: bool) -> None:
    """Hadron's runtime, copied unchanged out of its release disk image into
    dist/wine-arm64. Its loader (lib/wine/aarch64-unix/wine.app) is signed with
    a provisioning profile that grants the cross-architecture entitlement, so
    this step modifies nothing in the tree: no xattr pass (curl sets no
    quarantine). The mtld3d step afterwards swaps only mtld3d's files (see
    mtld3d.TARGETS), never the loader; the `mtld3d` pin vouches for those."""
    wine_home, _ = checkout.flavour_paths("arm64")
    pin = checkout.manifest["wine_arm64"]
    record = wine_home / WINE_RECORD
    if os.access(wine_home / "bin" / "wine", os.X_OK) and _recorded_sha(record) == pin["sha256"]:
        say("arm64 Wine already installed")
        return
    image = _download(checkout, pin["url"], pin["image"], pin["sha256"], "Hadron (arm64 Wine)",
                      verbose)
    say("copying the arm64 Wine runtime out of the disk image")
    staging = wine_home.with_name(wine_home.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    with _attached(image) as mount:
        runtime = mount / pin["runtime"]
        if not (runtime / "bin" / "wine").exists():
            raise DaocError(f"{pin['image']} has no Wine runtime at {pin['runtime']}")
        proc.run([DITTO, runtime, staging])
    atomic_write(staging / WINE_RECORD,
                 json.dumps({"image": pin["image"], "sha256": pin["sha256"]}) + "\n")
    if wine_home.exists():
        # install() checked only the current Wine, and before the download: a
        # client may have started since, or be running from this one anyway.
        try:
            _refuse_running(checkout, "install", wine_home)
        except DaocError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    shutil.rmtree(wine_home, ignore_errors=True)
    staging.rename(wine_home)


def _recorded_sha(record: Path) -> Optional[str]:
    try:
        return json.loads(record.read_text(encoding="utf-8")).get("sha256")
    except (OSError, ValueError, AttributeError):
        return None


def install_release(checkout: Checkout, game: Game,
                    fetch_url: Optional[release.Downloader] = None) -> None:
    """Bring the Client install to game: its Version's release (replaced, graphics
    carried over, when the install holds another one) and its Edition's game.dll."""
    pin = pins.effective(checkout, "original_client", game.version)
    version = pin["version"]
    _recover_swap(checkout)
    if not checkout.client_root.is_dir():
        say(f"fetching OfflineDAoC v{version} (this is a ~5 GB download)")
        replace = True
    else:
        _resume(checkout, "install")
        # Read from the install, not the pin: a pull can move the pin alone.
        built, matches = pins.built_from(checkout, "original_client", pin)
        replace = matches is False
        if replace:
            say(f"replacing OfflineDAoC {built} with the pinned v{version} "
                 "(this is a ~5 GB download)")
        else:
            say("OfflineDAoC already installed")
    if replace:
        saved = _replace(checkout, pin, fetch_url or release.download, "install", game.version)
        if saved is not None:
            restore(checkout, saved, "install")
    apply_edition(checkout, game, fetch_url)


def _edition_bytes(checkout: Checkout, game: Game, pin: Dict[str, Any],
                   fetch_url: release.Downloader) -> bytes:
    """The Edition's pristine game.dll: the Classic one from the install's own
    editions folder, else (and for the Sluaghbinder one) from the cached release."""
    root = pin["root_folder"]
    member = (pin.get("editions") or {}).get(game.edition, {}).get("game_dll_member") \
        or f"{root}/{GAME_DLL}"
    local = checkout.client_root / member[len(root) + 1:]
    if game.edition == "classic" and local.is_file():
        return local.read_bytes()
    archive = release.download_release(pin, checkout.downloads / f"v{pin['version']}",
                                       fetch_url=fetch_url)
    with zipfile.ZipFile(archive) as zf:
        try:
            return zf.read(member)
        except KeyError:
            raise DaocError(f"{archive.name} has no {member}") from None


def apply_edition(checkout: Checkout, game: Game,
                  fetch_url: Optional[release.Downloader] = None) -> bool:
    """Make the Client install hold game's Edition's game.dll (patched), without
    re-extracting the release; True when it swapped, False when it already did.
    A game.dll that is neither Edition's build of game's Version is left alone:
    the Client patch then refuses it as no Proven build."""
    want = games.edition_sha(checkout, game)
    dll = checkout.app_dir / "game.dll"
    orig = dll.with_name(dll.name + ".orig")
    record = pins.installed(checkout, "original_client") or {}
    current = sha256(orig if orig.is_file() else dll)
    if current == want:
        if record and record.get("edition") != game.edition:
            pins.record_installed(checkout, "original_client",
                                  dict(record, edition=game.edition, game_dll_sha256=want))
        return False
    known = {games.edition_sha(checkout, Game(game.version, e)) for e in games.EDITIONS}
    if current not in known:
        return False
    if want not in client_patch.PROVEN_BUILDS:
        raise DaocError(f"the {game.edition} game.dll ({want[:12]}) is not a Proven build; "
                        "it needs a shipped update")
    _refuse_running(checkout, "install")
    pin = pins.effective(checkout, "original_client", game.version)
    data = _edition_bytes(checkout, game, pin, fetch_url or release.download)
    if hashlib.sha256(data).hexdigest() != want:
        raise DaocError(f"the {game.edition} game.dll of OfflineDAoC v{pin['version']} does not "
                        f"match its pinned hash {want[:12]}; reinstall the client")
    say(f"game.dll -> the {games.EDITION_TITLES[game.edition]} edition")
    tmp = dll.with_name(dll.name + ".new")
    tmp.write_bytes(data)
    os.replace(tmp, dll)
    orig.unlink(missing_ok=True)
    client_patch.patch(dll)
    pins.record_installed(checkout, "original_client",
                          dict(record, edition=game.edition, game_dll_sha256=want))
    return True


def _patch_client(checkout: Checkout) -> None:
    # Always run: patch() works from game.dll.orig and is a no-op when game.dll
    # already holds the current spec, so an install patched by an older spec
    # gets the new edits.
    client_patch.patch(checkout.app_dir / "game.dll")


def _keep_profile_folders(users: Path) -> None:
    """Wine links the Windows profile folders (Documents, Desktop, ...) of every
    prefix user ("crossover" or the macOS user name) to the macOS home folders. The first
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


def _carry_settings(checkout: Checkout, flavour: str, users: Path) -> None:
    """Copy the client's settings into this prefix's user unless it has its own:
    from another user of this prefix (one made by another wine, e.g. Wine
    Staging), else from the other flavour's prefix, its own Wine's user first
    (a user left there by an older wine holds stale settings)."""
    owner = FLAVOURS[flavour].prefix_user()
    if not owner:
        return
    ea = Path("AppData") / "Roaming" / "Electronic Arts"
    dst = users / owner / ea
    if os.path.lexists(dst):
        return
    other = next(f for f in FLAVOURS if f != flavour)
    other_users = checkout.flavour_paths(other)[1] / "drive_c" / "users"
    theirs = FLAVOURS[other].prefix_user()
    for src in ([users / theirs, other_users / theirs] if theirs else []) + [other_users / owner]:
        if (src / ea).is_dir():
            say(f"copying client settings from {src} to {owner}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src / ea, dst, symlinks=True)
            return


# The client's own settings folder: paths.dat's `settings=` cut to 13 characters
# (OfflineDAoC035 -> OfflineDAoC03, the folder 1.127 creates in a fresh prefix).
SETTINGS_NAME_CHARS = 13
# The Game Options pane's sound sliders: item1 Sound Effects, item2 Music,
# item3 Ambient Sounds, item4 Ambient Music, each stored as 10 minus the level
# shown (0 Full, 10 Off): set in game to Off and 3, they are written as 10 and 7.
SOUND_OFF = b"[sound]\r\nitem1=10\r\nitem2=10\r\nitem3=10\r\nitem4=10\r\n"


def _settings_folder(checkout: Checkout) -> Optional[str]:
    try:
        text = (checkout.app_dir / "paths.dat").read_text(encoding="latin-1")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip().lower() == "settings" and value.strip():
            return value.strip()[:SETTINGS_NAME_CHARS]
    return None


def _default_sound_off(checkout: Checkout, flavour: str, users: Path) -> None:
    """Client sound starts off: a user.dat with no [sound] section gets every
    volume at 0. One that has it (set in game, written by the client, or carried
    over) is left alone."""
    owner = FLAVOURS[flavour].prefix_user()
    folder = _settings_folder(checkout)
    if not owner or not folder:
        return
    user_dat = (users / owner / "AppData" / "Roaming" / "Electronic Arts" / "Dark Age of Camelot"
                / folder / "user.dat")
    data = user_dat.read_bytes() if user_dat.is_file() else b""
    if any(line.strip().lower() == b"[sound]" for line in data.splitlines()):
        return
    end = b"" if not data or data.endswith(b"\n") else b"\r\n"
    atomic_write(user_dat, data + end + SOUND_OFF)
    say("client sound is off; turn it up in the game's Sound Options")


def _install_mtld3d(wine_home: Path, prefix: Path) -> None:
    """Hadron's mtld3d is a native d3d9.dll in the prefix (i386 in syswow64,
    ARM64X in system32) plus markers that let Wine load its mtld3d.dll builtin;
    the launch sets d3d9=n,b to pick it. Copied after `wineboot -u`, which would
    otherwise be free to put Wine's own d3d9 back."""
    src = wine_home / "lib" / "hadron" / "d3d9"
    win = prefix / "drive_c" / "windows"
    copies = [
        (src / "i386" / "d3d9.dll", win / "syswow64" / "d3d9.dll"),
        (src / "aarch64" / "d3d9.dll", win / "system32" / "d3d9.dll"),
        (src / "markers" / "syswow64" / "mtld3d.dll", win / "syswow64" / "mtld3d.dll"),
        (src / "markers" / "system32" / "mtld3d.dll", win / "system32" / "mtld3d.dll"),
    ]
    for s, d in copies:
        if not s.is_file():
            raise DaocError(f"the arm64 Wine has no {s.relative_to(wine_home)}; "
                            "reinstall it: rm -rf dist/wine-arm64 && daoc client install --wine arm64")
        if not d.is_file() or d.read_bytes() != s.read_bytes():
            shutil.copyfile(s, d)


def _check_local_network(wine: str, wineserver: str, env: Mapping[str, str]) -> None:
    """A fresh Wine session resolves the Mac's own name first. While macOS holds
    the arm64 Wine's Local Network access (prompt unanswered or denied) that
    lookup waits ~35 s and fails, on every client start."""
    _, output = _wine_output([wine, "cmd", "/c", "exit"],
                             dict(env, WINEDEBUG="-all,err+winediag"))
    _wine_output([wineserver, "-w"], env)
    if LOCAL_NETWORK_MISS in output:
        say("macOS is holding the arm64 Wine's Local Network access, which adds ~35 s to every "
            "client start: allow \"wine\" in System Settings > Privacy & Security > Local "
            "Network (or answer its prompt), then run daoc client install --wine arm64 again "
            "to check")


def _init_prefix(checkout: Checkout, flavour: str, verbose: bool) -> None:
    wine_home, prefix = checkout.flavour_paths(flavour)
    arm64 = wine_is_arm64(wine_home)
    wine = str(wine_home / "bin" / "wine")
    wineserver = str(wine_home / "bin" / "wineserver")
    env = wine_env(wine_home, prefix)
    if not (prefix / "system.reg").is_file():
        say("initializing wine prefix (win10 version)")
        prefix.mkdir(parents=True, exist_ok=True)
        _wine([wine, "wineboot", "-i"], env, verbose)
        _wine([wine, "reg", "add", "HKCU\\Software\\Wine", "/v", "Version", "/d", "win10", "/f"],
              env, verbose, check=False)
        # Wait for wineserver to flush the registry hives before checking them.
        _wine([wineserver, "-w"], env, verbose)
        if not (prefix / "system.reg").is_file():
            raise DaocError("wine prefix init failed")
    else:
        say("wine prefix already initialized")
    # Bring an existing prefix (e.g. one made by an older wine) up to this
    # wine's version now, so its first game launch does not do it.
    _wine([wine, "wineboot", "-u"], env, verbose)
    _wine([wineserver, "-w"], env, verbose)

    users = prefix / "drive_c" / "users"
    if users.is_dir():
        _keep_profile_folders(users)
        _carry_settings(checkout, flavour, users)
        _default_sound_off(checkout, flavour, users)
    if arm64:
        _install_mtld3d(wine_home, prefix)
        _check_local_network(wine, wineserver, env)


def _install_launcher(checkout: Checkout) -> None:
    """The Launcher bundle resolves paths relative to its own location, so it
    is copied next to the Client install."""
    dst = checkout.launcher_app
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(checkout.launcher_src, dst, symlinks=True)
    _unquarantine(dst)


def install(checkout: Checkout, flavour: Optional[str] = None, verbose: bool = False,
            game: Optional[Game] = None, download_only: bool = False) -> None:
    """Install or complete the Client install for game (default: the selected
    one) with the flavour's Wine (default: the current one); finished steps are
    skipped. The flavour is recorded last, so `daoc client start` switches only
    after a complete install. download_only fetches and verifies the release
    into downloads/ and changes nothing else."""
    game = game or selection.load(checkout).game
    if download_only:
        pin = pins.effective(checkout, "original_client", game.version)
        release.download_release(pin, checkout.downloads / f"v{pin['version']}")
        return
    if flavour is None:
        flavour = current = checkout.flavour
    else:
        try:
            current = checkout.flavour
        except DaocError:
            # --wine replaces a bad record without reading it; until install
            # rewrites it, the Wine being installed is this checkout's.
            checkout.assume_flavour(flavour)
            current = flavour
    version = pins.effective(checkout, "original_client", game.version)["version"]
    say(f"client install: OfflineDAoC v{version} + {FLAVOURS[flavour].title}")
    _requirements(checkout, flavour)
    # Before anything touches Wine or game.dll, and while checkout still names
    # the current Wine: a flavour switch would orphan the running client.
    _refuse_running(checkout, "install")
    checkout.downloads.mkdir(parents=True, exist_ok=True)
    checkout.client_root.parent.mkdir(parents=True, exist_ok=True)
    _install_wine(checkout, flavour, verbose)
    _apply_mtld3d_choice(checkout, flavour)
    install_release(checkout, game)
    _patch_client(checkout)
    _init_prefix(checkout, flavour, verbose)
    _install_launcher(checkout)
    atomic_write(checkout.flavour_file, flavour + "\n")
    if flavour != current:
        say(f"daoc client start now uses the {flavour} Wine "
            f"(switch back with: daoc client install --wine {current})")
    say("client install: done; launch the game (server running) with: daoc client start")
