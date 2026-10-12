"""argv-only subprocess helpers. Nothing here ever goes through a shell.

run() is for steps whose output is noise unless they fail: without --verbose it
captures the child's stdout and stderr and replays both to stderr only when the
step fails. execv() replaces daoc with a passthrough tool, so TUIs keep the TTY
and signals reach the child directly.
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, NoReturn, Optional, Sequence, Union

from daoc_cli.errors import DaocError

StrPath = Union[str, "os.PathLike[str]"]


def _argv(argv: Sequence[StrPath]) -> list:
    if isinstance(argv, (str, bytes)) or not argv:
        raise TypeError("argv must be a non-empty list of arguments")
    return [os.fspath(a) for a in argv]


def run(
    argv: Sequence[StrPath],
    *,
    cwd: Optional[StrPath] = None,
    env: Optional[Mapping[str, str]] = None,
    verbose: bool = False,
    check: bool = True,
) -> "subprocess.CompletedProcess[str]":
    """Run argv and wait for it.

    verbose: the child inherits stdout/stderr (the result's stdout/stderr are None).
    Otherwise both are captured as text into the result. With check, a non-zero
    exit replays the captured stdout then stderr to stderr and raises DaocError;
    without check the caller judges the result and nothing is replayed.
    """
    args = _argv(argv)
    name = Path(args[0]).name
    pipe = None if verbose else subprocess.PIPE
    try:
        result = subprocess.run(
            args, cwd=cwd, env=env, stdout=pipe, stderr=pipe, text=True, errors="replace"
        )
    except OSError as e:
        raise DaocError(f"cannot run {args[0]}: {e.strerror or e}") from None
    if check and result.returncode != 0:
        for captured in (result.stdout, result.stderr):
            if captured:
                sys.stderr.write(captured)
                if not captured.endswith("\n"):
                    sys.stderr.write("\n")
        sys.stderr.flush()
        if result.returncode < 0:
            raise DaocError(f"{name} was killed by signal {-result.returncode}")
        raise DaocError(f"{name} failed (exit {result.returncode})")
    return result


def execv(
    argv: Sequence[StrPath],
    *,
    cwd: Optional[StrPath] = None,
    env: Optional[Mapping[str, str]] = None,
) -> NoReturn:
    """Replace this process with argv. argv[0] is a path: there is no PATH lookup."""
    args = _argv(argv)
    sys.stdout.flush()
    sys.stderr.flush()
    if cwd is not None:
        try:
            os.chdir(cwd)
        except OSError as e:
            raise DaocError(f"cannot enter {os.fspath(cwd)}: {e.strerror or e}") from None
    try:
        if env is None:
            os.execv(args[0], args)
        else:
            os.execve(args[0], args, env)
    except OSError as e:
        raise DaocError(f"cannot run {args[0]}: {e.strerror or e}") from None
