"""Latest upstream pins, and `daoc <group> update --check`.

resolve_latest asks GitHub (unauthenticated) for each group's
latest upstream and returns it in the shape of that group's manifest.json entry:
  - server: the `main` sha of manifest `server.upstream`.
  - client: the latest release of the repo in `client.release_url`, plus its
    download-manifest.json for the root folder, archive hash and size, and the
    part names, sizes and hashes. The pristine game.dll hash is only known
    after a download, so it is kept from the current pin when the version is
    unchanged and is None otherwise.
  - graphics: the `main` sha of `graphics.repo`, resolved from that repo itself
    so the sha always comes from the repo that is then cloned.

check prints one line per group and changes nothing: no pin, install or
Local pin file is written.
"""
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from daoc_cli import pins
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

API = "https://api.github.com/repos"
USER_AGENT = "daoc-macos-installer/1.0"

# The pin field that says whether two pins are the same upstream state.
_KEY = {"server": "ref", "client": "version", "graphics": "ref"}


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
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


def _latest_client(checkout: Checkout) -> Dict[str, Any]:
    shipped = pins.shipped(checkout, "client")
    owner, repo = _repo(shipped["release_url"], "client.release_url")
    tag = _get_json(f"{API}/{owner}/{repo}/releases/latest").get("tag_name")
    if not isinstance(tag, str) or not tag:
        raise DaocError(f"GitHub returned no tag for the latest {owner}/{repo} release")
    version = tag[1:] if tag.startswith("v") else tag
    release_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/"
    asset = shipped.get("manifest_asset") or "download-manifest.json"
    # Cross-check the new release's manifest before reporting it as a pin.
    rm = _get_json(release_url + asset)
    try:
        if rm["Version"] != version:
            raise DaocError(f"{asset} of {tag} says version {rm['Version']!r}, not {version!r}")
        parts = [{"name": p["Name"], "bytes": p["Bytes"], "sha256": p["SHA256"]}
                 for p in rm["Parts"]]
        fields = {
            "release_url": release_url,
            "version": version,
            "manifest_asset": asset,
            "root_folder": rm["RootFolder"],
            "archive_sha256": rm["ArchiveSHA256"],
            "archive_bytes": rm["ArchiveBytes"],
            "parts": parts,
        }
    except (KeyError, TypeError) as e:
        raise DaocError(f"{asset} of {tag} is missing {e}") from None
    # The pristine game.dll hash must be re-derived for a new release.
    current = [pins.local(checkout, "client"), shipped]
    fields["game_dll_sha256"] = next(
        (p.get("game_dll_sha256") for p in current if p and p.get("version") == version), None)
    return fields


def resolve_latest(checkout: Checkout, group: str) -> Dict[str, Any]:
    """The group's latest upstream pin, in its manifest entry's shape."""
    if group == "server":
        url = pins.shipped(checkout, "server")["upstream"]
        return {"upstream": url, "ref": _main_sha(*_repo(url, "server.upstream"))}
    if group == "client":
        return _latest_client(checkout)
    if group == "graphics":
        url = pins.shipped(checkout, "graphics")["repo"]
        return {"repo": url, "ref": _main_sha(*_repo(url, "graphics.repo"))}
    raise DaocError(f"no pin group {group!r} (expected one of: {', '.join(pins.GROUPS)})")


def same(group: str, a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> bool:
    """Whether two pins name the same upstream state (ref, or client version)."""
    return bool(a and b) and a.get(_KEY[group]) == b.get(_KEY[group])


def check(checkout: Checkout, group: str) -> int:
    """Print `<group>  Shipped … Local … built from … latest … <verdict>`; exit 0."""
    from daoc_cli import overview  # overview imports server, which imports this module

    shipped = pins.shipped(checkout, group)
    # pins.local, not pins.effective: a lapsed Local pin is reported, never dropped here.
    local = pins.local(checkout, group)
    pin = local if local is not None else shipped
    built, _ = overview._built_from(checkout, group, pin)
    latest = resolve_latest(checkout, group)
    verdict = "up to date" if same(group, pin, latest) else "UPDATE AVAILABLE"
    print(
        f"{group:<8}  Shipped {pins.short(group, shipped)}  "
        f"Local {pins.short(group, local) if local is not None else '-'}  "
        f"built from {built}  latest {pins.short(group, latest)}  {verdict}"
    )
    return 0
