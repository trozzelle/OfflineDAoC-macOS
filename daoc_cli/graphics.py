"""`daoc graphics …`: optional graphical patches for the installed client, from
the pinned OfflineDAoC-macOS-graphics project (the graphics pin).

Everything after `graphics` goes to the pinned daoc-gfx untouched; no
arguments means `select` (the checklist). Nothing here runs unless called:
client install never pulls the graphics project. The first call clones the
pinned commit into upstream/graphics/; every call checks that checkout is at
the pin with no local changes (its d3d9.dll ends up loaded by the game), then
runs its daoc-gfx against this Checkout's client, wine, prefix and installed
launcher (DAOC_WINE_HOME / DAOC_WINEPREFIX override wine and prefix, as they
do for the launcher). Each patch, and what turning it off restores, is in the
graphics project's README.

`graphics update` is daoc's own action and never reaches daoc-gfx: it moves
the Local graphics pin to the project's `main` once that commit passes the
contract check (its own tests, plus the daoc-gfx options, launcher line and
machine interface this Checkout relies on).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from daoc_cli import pins, proc, updates
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError, say

PYTHON = "/usr/bin/python3"

# The anisotropy patch rewrites the WINEDLLOVERRIDES line of the installed
# launcher only if that line equals its STOCK_LINE exactly once; checked against
# the source launcher (Checkout.launcher_src).
LAUNCH_SCRIPT = Path("Contents") / "MacOS" / "launch"
# daoc-gfx `status --json` keys this Checkout reads (schema 1).
STATUS_SCHEMA = 1
STATUS_KEYS = ("patches", "anisotropy_level", "mtld3d_conf", "textures")


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser(
        "graphics",
        help="optional graphics patches (daoc-gfx passthrough)",
        description="Run the pinned daoc-gfx against this checkout's client; "
        "no arguments opens the patch checklist (select).",
    )
    p.set_defaults(func=handle)


def ensure_checkout(checkout: Checkout) -> Path:
    """Make checkout.graphics_src a clean clone at the effective graphics pin;
    return it. Status lines go to stderr."""
    pin = pins.effective(checkout, "graphics")
    repo, ref = pin["repo"], pin["ref"]
    src = checkout.graphics_src
    if not (src / ".git").is_dir():
        say(f"graphics: cloning {repo.rstrip('/').rsplit('/', 1)[-1]} at {ref[:12]}")
        src.parent.mkdir(parents=True, exist_ok=True)
        proc.run(["git", "clone", "--quiet", repo, str(src)])
    # Refuse edited or untracked files: they would run (or, for d3d9.dll, be
    # copied next to game.dll) as if they were the pinned commit.
    if proc.git(src, "status", "--porcelain").stdout.strip():
        raise DaocError(
            f'{src} has local changes (git -C "{src}" status); '
            "remove that folder to re-clone the pinned commit"
        )
    if proc.head(src) != ref:
        say(f"graphics: checking out pinned {ref[:12]}")
        proc.git(src, "fetch", "--quiet", "origin")
        proc.git(src, "checkout", "--quiet", "--detach", ref)
    actual = proc.head(src)
    if actual != ref:
        raise DaocError(f"{src} is at {actual[:12]}, pinned {ref[:12]}")
    return src


def gfx_argv(checkout: Checkout, src: Path, args: list) -> list:
    """The daoc-gfx at src against this Checkout's client, wine, prefix and
    launcher; no args means `select`."""
    return [
        PYTHON, str(src / "daoc-gfx"),
        "--app", str(checkout.app_dir),
        "--wine", str(checkout.wine_home),
        "--prefix", str(checkout.prefix),
        "--launcher", str(checkout.launcher_app),
        *(args or ["select"]),
    ]


def gfx(checkout: Checkout, args: list) -> "subprocess.CompletedProcess[str]":
    """Run the pinned daoc-gfx with args (see gfx_argv); stdout and stderr are
    captured and the caller judges the exit."""
    return proc.run(gfx_argv(checkout, ensure_checkout(checkout), args), check=False)


def _lists(help_text: str, word: str) -> bool:
    """Whether help_text names word as a whole option or command."""
    return re.search(rf"(^|[^-\w]){re.escape(word)}([^-\w]|$)", help_text, re.M) is not None


def _help(src: Path, *args: str) -> str:
    """`daoc-gfx <args> --help` output, or "" when it fails."""
    r = proc.run([PYTHON, str(src / "daoc-gfx"), *args, "--help"], check=False)
    return r.stdout + r.stderr if r.returncode == 0 else ""


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else "no output"


def contract_check(src: Path, checkout: Checkout) -> None:
    """Check that the daoc-gfx clone at src still keeps the contract this
    Checkout relies on. Raises DaocError naming the first failing check."""
    at = proc.head(src)[:12]

    def broken(check: str, why: str) -> DaocError:
        return DaocError(f"graphics contract check '{check}' fails at {at}: {why}; pin unchanged")

    # 1. The commit's own tests. Captured: replayed on failure, skips surfaced.
    r = proc.run([PYTHON, "-m", "unittest", "discover", "-v", "-s", "tests"], cwd=src, check=False)
    if r.returncode != 0:
        proc.replay(r.stdout, r.stderr)
        raise broken("tests", f"{PYTHON} -m unittest discover -s tests exits {r.returncode}")
    for line in (r.stdout + r.stderr).splitlines():
        if "... skipped" in line:
            print(line, file=sys.stderr)
    say(f"graphics tests pass at {at}")

    # 2. The options and default command gfx_argv passes.
    top = _help(src)
    for word in ("--app", "--wine", "--prefix", "--launcher", "select"):
        if not _lists(top, word):
            raise broken("daoc-gfx --help", f"it no longer lists {word}")

    # 3. The anisotropy patch's STOCK_LINE against this Checkout's launcher.
    r = proc.run([PYTHON, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                  "from daoc_gfx.anisotropy import STOCK_LINE; sys.stdout.write(STOCK_LINE)",
                  str(src)], check=False)
    if r.returncode != 0:
        raise broken("STOCK_LINE", f"cannot read daoc_gfx.anisotropy.STOCK_LINE: {_last_line(r.stderr)}")
    script = checkout.launcher_src / LAUNCH_SCRIPT
    try:
        lines = [line.strip() for line in script.read_text(encoding="utf-8").splitlines()]
    except OSError as e:
        raise broken("STOCK_LINE", f"cannot read {script}: {e.strerror or e}") from None
    count = lines.count(r.stdout)
    if count != 1:
        raise broken("STOCK_LINE", f"daoc_gfx.anisotropy.STOCK_LINE occurs {count} times in "
                     f"{script}, not once ({r.stdout})")
    say(f"daoc-gfx options and launcher line match at {at}")

    with tempfile.TemporaryDirectory(prefix="daoc-gfx-check-") as tmp:
        app = Path(tmp) / "app"
        app.mkdir()
        (app / "game.dll").write_bytes(b"")
        launcher = Path(tmp) / checkout.launcher_src.name
        shutil.copytree(checkout.launcher_src, launcher, symlinks=True)

        # 4. The machine-readable status a client update carries over.
        r = proc.run([PYTHON, str(src / "daoc-gfx"), "--app", str(app), "--launcher", str(launcher),
                      "status", "--json"], check=False)
        if r.returncode != 0:
            raise broken("status --json", f"exits {r.returncode}: {_last_line(r.stderr)}")
        try:
            status = json.loads(r.stdout)
        except ValueError as e:
            raise broken("status --json", f"stdout is not JSON ({e})") from None
        if not isinstance(status, dict) or status.get("schema") != STATUS_SCHEMA:
            schema = status.get("schema") if isinstance(status, dict) else None
            raise broken("status --json", f"schema is {schema!r}, not {STATUS_SCHEMA}")
        missing = [k for k in STATUS_KEYS if k not in status]
        if missing:
            raise broken("status --json", f"it has no {', '.join(missing)}")

        # 5. The texture-pack export and install a client update carries over with.
        if not _lists(_help(src, "--app", str(app), "textures"), "export"):
            raise broken("textures --help", "it no longer lists export")
        if not _lists(_help(src, "--app", str(app), "textures", "install"), "--from-dir"):
            raise broken("textures install --help", "it no longer lists --from-dir")
    say(f"daoc-gfx machine interface matches at {at}")


def update(checkout: Checkout) -> int:
    """Move the Local graphics pin to the project's `main` if that commit
    passes contract_check; otherwise leave the pin as it is."""
    current = pins.effective(checkout, "graphics")
    latest = updates.resolve_latest(checkout, "graphics")
    sha = latest["ref"]
    if sha == current.get("ref"):
        say(f"graphics already at {sha[:12]}")
        return 0
    with tempfile.TemporaryDirectory(prefix="daoc-graphics-") as tmp:
        src = Path(tmp) / "graphics"
        say(f"graphics: checking main at {sha[:12]} in a temp clone")
        proc.run(["git", "clone", "--quiet", latest["repo"], str(src)])
        proc.git(src, "checkout", "--quiet", "--detach", sha)
        contract_check(src, checkout)
    pins.set_local(checkout, "graphics", {**pins.shipped(checkout, "graphics"), **latest})
    print(f"graphics pin -> {sha[:12]} (Local pin); the next daoc graphics … call checks it out",
          file=sys.stderr)
    return 0


def handle(args: argparse.Namespace, checkout: Checkout) -> int:
    passthrough = list(args.passthrough or [])
    if passthrough[:1] == ["update"]:
        if passthrough[1:] == ["--check"]:
            return updates.check(checkout, "graphics")
        if passthrough[1:]:
            raise DaocError("usage: daoc graphics update [--check]", 2)
        return update(checkout)
    if not (checkout.app_dir / "game.dll").is_file():
        raise DaocError(f"no client in {checkout.app_dir} — run daoc client install")
    src = ensure_checkout(checkout)
    # No chdir: relative --archives paths, the checklist's archive prompt and
    # relative DAOC_WINE_HOME / DAOC_WINEPREFIX resolve against the caller's
    # directory (Checkout already resolved the env overrides against it).
    proc.execv(gfx_argv(checkout, src, passthrough))
