"""Latest upstream pins, and `daoc <group> update --check`.

Updates stay within the selected game Version. resolve_latest asks GitHub
(unauthenticated) for a pin's latest upstream and returns it in the shape of
its manifest.json entry:
  - server: the `main` sha of the Version's `server.upstream`, but only while
    that commit says it is synced to the Version (OfflineDaocVersion in the
    fork's admin host, MARKER_PATHS); otherwise OtherVersion: a newer game
    Version needs a daoc release, not a Local pin.
  - original_client / new_client: the Version's pinned release tag re-read, since
    upstream can replace a tag's assets. The editions' pristine game.dll hashes
    are kept only while the archive is the same one.
  - graphics: the `main` sha of `graphics.repo`, resolved from that repo itself
    so the sha always comes from the repo that is then cloned.
newer_upstream names a game Version upstream released that this daoc release
doesn't support yet.

check prints one line per pin and changes nothing: no pin, install or Local
pin file is written.
"""
import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from daoc_cli import games, pins, release
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

API = "https://api.github.com/repos"


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": release.USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise DaocError(
                f"GitHub API rate limit reached (HTTP {e.code} from {url}); unauthenticated "
                "requests are limited to 60 an hour, so try again later"
            ) from None
        raise DaocError(f"{url}: HTTP {e.code} {e.reason}") from None
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {url}: {e}") from None


def _repo(url: str, what: str) -> Tuple[str, str]:
    """(owner, repo) of a https://github.com/<owner>/<repo>[/...] URL."""
    prefix = "https://github.com/"
    parts = url[len(prefix):].strip("/").split("/") if url.startswith(prefix) else []
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise DaocError(f"{what} is not a https://github.com/<owner>/<repo> URL: {url}")
    repo = parts[1][:-len(".git")] if parts[1].endswith(".git") else parts[1]
    return parts[0], repo


def _main_sha(owner: str, repo: str) -> str:
    sha = _get_json(f"{API}/{owner}/{repo}/commits/main").get("sha")
    if not isinstance(sha, str) or not sha:
        raise DaocError(f"GitHub returned no sha for {owner}/{repo} main")
    return sha


# Where the server fork names the game Version a commit is synced to: the admin
# host's OfflineDaocVersion, in its 0.36 layout first, then the 0.35 one.
MARKER_PATHS = ("src/Admin.Host/AdminService.cs", "src/GameServer/admin/AdminService.cs")
_MARKER = re.compile(r'OfflineDaocVersion\s*=\s*"(\d+\.\d+)"')
_TAG = re.compile(r"v(\d+\.\d+)[bc]?")
NOT_YET = "this daoc release doesn't support it yet"


class OtherVersion(DaocError):
    """The fork's latest commit is synced to another game Version than the selected one."""

    def __init__(self, found: Optional[str], version: Optional[str]) -> None:
        what = f"is now {found}" if found else "names no game version"
        super().__init__(f"fork main {what}; {NOT_YET} (selected game version {version})", 2)
        self.found = found


def _get_text(url: str) -> Optional[str]:
    """A raw file's text; None when it does not exist (HTTP 404)."""
    req = urllib.request.Request(url, headers={"User-Agent": release.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise DaocError(f"{url}: HTTP {e.code} {e.reason}") from None
    except OSError as e:
        raise DaocError(f"cannot read {url}: {e}") from None


def fork_version(upstream: str, ref: str) -> Optional[str]:
    """The game Version the fork's commit ref says it is synced to; None when it names none."""
    owner, repo = _repo(upstream, "server.upstream")
    for path in MARKER_PATHS:
        text = _get_text(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}")
        match = _MARKER.search(text or "")
        if match:
            return match.group(1)
    return None


def _release_manifest(shipped: Dict[str, Any], what: str) -> Tuple[Any, str]:
    """(the pinned tag's download-manifest.json, its asset name), re-read from upstream."""
    asset = release.plain_name(shipped.get("manifest_asset") or "download-manifest.json",
                               "manifest_asset")
    rm = _get_json(shipped["release_url"] + asset)
    if not isinstance(rm, dict) or rm.get("Version") != shipped["version"]:
        found = rm.get("Version") if isinstance(rm, dict) else None
        raise DaocError(f"{asset} of v{shipped['version']} ({what}) says version {found!r}, "
                        f"not {shipped['version']!r}")
    return rm, asset


def _parts(rm: Dict[str, Any], asset: str) -> List[Dict[str, Any]]:
    return [{"name": release.plain_name(p["Name"], f"{asset} part"),
             "bytes": p["Bytes"], "sha256": str(p["SHA256"]).lower()}
            for p in rm["Parts"]]


def _latest_original(checkout: Checkout, version: str) -> Dict[str, Any]:
    """The Version's pinned release tag, re-read: the same tag can carry new assets."""
    shipped = pins.shipped(checkout, "original_client", version)
    rm, asset = _release_manifest(shipped, "original client")
    if rm.get("Mode") == "edition":
        raise DaocError(f"{asset} of v{shipped['version']} is an edition overlay, not a release; "
                        "the original client pins the b release")
    try:
        fields = {
            "release_url": shipped["release_url"],
            "version": shipped["version"],
            "manifest_asset": asset,
            "root_folder": release.plain_name(rm["RootFolder"], f"{asset} RootFolder"),
            "archive_sha256": rm["ArchiveSHA256"],
            "archive_bytes": rm["ArchiveBytes"],
            "parts": _parts(rm, asset),
        }
    except (KeyError, TypeError) as e:
        raise DaocError(f"{asset} of v{shipped['version']} is missing {e}") from None
    # The editions' pristine game.dll hashes are only known for the archive they came from.
    current = [pins.local(checkout, "original_client", version), shipped]
    fields["editions"] = next((p.get("editions") for p in current
                               if p and p.get("archive_sha256") == fields["archive_sha256"]), None)
    return fields


def _latest_new(checkout: Checkout, version: str) -> Dict[str, Any]:
    shipped = pins.shipped(checkout, "new_client", version)
    rm, asset = _release_manifest(shipped, "new client")
    if rm.get("Mode") != "newclient":
        raise DaocError(f"{asset} of v{shipped['version']} is not a new-client release")
    try:
        return {
            "release_url": shipped["release_url"],
            "version": shipped["version"],
            "manifest_asset": asset,
            "root_folder": release.plain_name(rm["RootFolder"], f"{asset} RootFolder"),
            "unpacked_bytes": rm["UnpackedBytes"],
            "parts": _parts(rm, asset),
            "godot": shipped["godot"],
        }
    except (KeyError, TypeError) as e:
        raise DaocError(f"{asset} of v{shipped['version']} is missing {e}") from None


def resolve_latest(checkout: Checkout, group: str, version: Optional[str] = None) -> Dict[str, Any]:
    """The pin's latest upstream, in its manifest entry's shape. The server
    follows the fork's main only while main is synced to version (else
    OtherVersion); the clients re-read version's pinned release tags."""
    if group == "server":
        url = pins.shipped(checkout, "server", version)["upstream"]
        sha = _main_sha(*_repo(url, "server.upstream"))
        found = fork_version(url, sha)
        if found != version:
            raise OtherVersion(found, version)
        return {"upstream": url, "ref": sha}
    if group == "original_client":
        return _latest_original(checkout, version)
    if group == "new_client":
        return _latest_new(checkout, version)
    if group == "graphics":
        url = pins.shipped(checkout, "graphics")["repo"]
        return {"repo": url, "ref": _main_sha(*_repo(url, "graphics.repo"))}
    raise DaocError(f"no update for pin group {group!r}")


def newer_upstream(checkout: Checkout) -> Optional[str]:
    """The newest game Version upstream has released that this daoc release
    doesn't know, as of upstream's last 30 releases; None when there is none."""
    known = games.versions(checkout)
    shipped = pins.shipped(checkout, "original_client", known[-1])
    owner, repo = _repo(shipped["release_url"], "original_client.release_url")
    newest = None
    for entry in _get_json(f"{API}/{owner}/{repo}/releases?per_page=30") or []:
        match = _TAG.fullmatch(str((entry or {}).get("tag_name", "")))
        if not match or match.group(1) in known:
            continue
        candidate = match.group(1)
        if games.order(candidate) > games.order(known[-1]) and (
                newest is None or games.order(candidate) > games.order(newest)):
            newest = candidate
    return newest


def check(checkout: Checkout, group: str, version: Optional[str] = None) -> int:
    """Print `<pin>  Shipped … Local … built from … latest … <verdict>` and, for a
    game version's pins, a note naming a newer upstream Version; exit 0."""
    shipped = pins.shipped(checkout, group, version)
    # pins.local, not pins.effective: a lapsed Local pin is reported, never dropped here.
    local = pins.local(checkout, group, version)
    pin = local if local is not None else shipped
    built, _ = pins.built_from(checkout, group, pin)
    line = (f"{pins.label(group, version):<8}  Shipped {pins.short(group, shipped)}  "
            f"Local {pins.short(group, local) if local is not None else '-'}  "
            f"built from {built}  ")
    try:
        latest = resolve_latest(checkout, group, version)
    except OtherVersion as e:
        line += e.msg.split(" (selected")[0]
    else:
        verdict = "up to date" if pins.same(group, pin, latest) else "UPDATE AVAILABLE"
        line += f"latest {pins.short(group, latest)}  {verdict}"
    if group in pins.VERSIONED:
        newer = newer_upstream(checkout)
        if newer:
            line += f"  ({newer} is out upstream; {NOT_YET})"
    print(line)
    return 0
