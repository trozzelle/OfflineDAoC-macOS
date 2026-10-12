"""File helpers: chunked SHA-256, atomic replacement, and reading a growing log."""
import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional


def sha256_of(stream: BinaryIO) -> str:
    """Hex sha256 of everything left in stream, read in 1 MiB chunks."""
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return sha256_of(f)


def size(path: Path) -> int:
    """path's size in bytes; 0 when it cannot be read (e.g. no log yet)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def tail(path: Path, offset: int) -> str:
    """path's text from byte offset on; "" when it cannot be read."""
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def atomic_write(path: Path, text: str, mode: Optional[int] = None) -> None:
    """Replace path with text through a temp file in the same directory.

    The parent directory is created on demand. The file gets mode when given;
    otherwise an existing file's mode is kept and a new file gets 0o666 less
    the umask.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o7777
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
