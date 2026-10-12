"""Test harness: temp Checkouts, PATH stubs, real git, and in-process cli.main runs.

Run from the Checkout root: /usr/bin/python3 -m unittest discover -s tests
"""
import io
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daoc_cli import cli  # noqa: E402

STUB_LOG = "calls.log"

# Real git without the user's or the system's config (commit signing, hooks,
# url rewrites), and with a fixed identity. Also pass it to cli runs that make
# daoc run git.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(*args: str, cwd: Optional[Union[str, Path]] = None) -> str:
    """git args (with GIT_ENV) in cwd; its stripped stdout."""
    return subprocess.run(["git", *args], cwd=cwd, env=dict(os.environ, **GIT_ENV),
                          check=True, capture_output=True, text=True).stdout.strip()


def make_checkout(tmp: Union[str, Path]) -> Path:
    """Copy daoc, daoc_cli/, manifest.json and version.txt into <tmp>/checkout; no installs."""
    root = Path(tmp) / "checkout"
    root.mkdir(parents=True)
    shutil.copy2(ROOT / "daoc", root / "daoc")
    shutil.copytree(ROOT / "daoc_cli", root / "daoc_cli",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "manifest.json", root / "manifest.json")
    shutil.copy2(ROOT / "version.txt", root / "version.txt")
    return root


def path_stubs(tmp: Union[str, Path], stubs: Mapping[str, str]) -> Path:
    """Write executable sh stubs into <tmp>/stubs and return that directory.

    Each stub first appends its name and argv to <dir>/calls.log (read them back
    with stub_calls), then runs its body. Arguments must not contain newlines.
    """
    stub_dir = Path(tmp) / "stubs"
    stub_dir.mkdir(parents=True, exist_ok=True)
    log = shlex.quote(str(stub_dir / STUB_LOG))
    for name, body in stubs.items():
        path = stub_dir / name
        path.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\037' {shlex.quote(name)} \"$@\" >> {log}\n"
            f"printf '\\n' >> {log}\n"
            f"{body}\n"
        )
        path.chmod(0o755)
    return stub_dir


def stub_calls(stub_dir: Union[str, Path]) -> List[List[str]]:
    """Calls recorded by path_stubs stubs, oldest first: [[name, arg, ...], ...]."""
    log = Path(stub_dir) / STUB_LOG
    if not log.exists():
        return []
    return [line.split("\x1f")[:-1] for line in log.read_text().splitlines()]


def run_cli(
    argv: Sequence[str],
    checkout_root: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[int, str, str]:
    """cli.main(argv) in-process; returns (exit code, stdout, stderr).

    env is applied over os.environ for the call (None removes a variable) and
    os.environ is restored afterwards.
    """
    saved = dict(os.environ)
    out, err = io.StringIO(), io.StringIO()
    try:
        for key, value in (env or {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv), root=checkout_root)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return code, out.getvalue(), err.getvalue()
