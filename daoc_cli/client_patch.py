"""The Client patch: the connect.exe-equivalent no-encryption patch to game.dll.

Only a Proven build is patched: PROVEN_BUILDS maps the sha256 of a pristine
game.dll to the patch spec proven against it, and any other pristine hash is
refused instead of silently corrupted. The current spec (see the upstream
analysis in the porting notes):
  - NOP 10 bytes at file offset 0x11035 (kills `mov dword [0x10477ac], 3`)
  - set the byte at file offset 0x1102b to 0x01 (state immediate 2 -> 1)

The pristine DLL is kept next to the target as game.dll.orig (created on first
run) and every run patches from it, byte-verified. A game.dll without .orig
whose bytes already match a spec's patched output is accepted as already
patched (a client patched before the .orig convention); anything else that is
not a Proven build is refused.
"""
import hashlib
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Mapping, NamedTuple, Optional, Tuple

from daoc_cli.errors import DaocError


class Edit(NamedTuple):
    """Replace `original` with `patched` at file offset `offset`."""

    offset: int
    original: bytes
    patched: bytes
    what: str


PatchSpec = Tuple[Edit, ...]

NO_ENCRYPTION: PatchSpec = (
    Edit(0x11035, bytes.fromhex("c705ac77040103000000"), b"\x90" * 10,
         "NOP `mov dword [0x10477ac], 3`"),
    Edit(0x1102B, b"\x02", b"\x01", "state immediate 0x02 -> 0x01"),
)

# Pristine game.dll sha256 -> the patch proven against that build.
PROVEN_BUILDS: Dict[str, PatchSpec] = {
    # OfflineDAoC v0.35b, the Sluaghbinder client.
    "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b": NO_ENCRYPTION,
}


def _say(msg: str) -> None:
    print(f"daoc: {msg}", file=sys.stderr, flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_patched(data: bytes, spec: PatchSpec) -> bool:
    return all(data[e.offset:e.offset + len(e.patched)] == e.patched for e in spec)


def _apply(data: bytearray, spec: PatchSpec) -> List[str]:
    """Patch data in place from the pristine bytes and return what was done; a
    region already holding its patched bytes is left alone, any other content
    is refused."""
    done = []
    for e in spec:
        end = e.offset + len(e.original)
        found = bytes(data[e.offset:end])
        if found == e.original:
            data[e.offset:end] = e.patched
            done.append(f"patched 0x{e.offset:x}: {e.what}")
        elif found == e.patched:
            done.append(f"0x{e.offset:x} already patched ({e.what})")
        else:
            raise DaocError(f"unexpected bytes at 0x{e.offset:x} in the pristine game.dll: "
                            f"{found.hex(' ')}")
    return done


def patch(dll: Path, proven: Optional[Mapping[str, PatchSpec]] = None) -> bool:
    """Apply the Client patch to dll; returns False when it was already patched.

    proven defaults to PROVEN_BUILDS (tests pass their own).
    """
    proven = PROVEN_BUILDS if proven is None else proven
    orig = dll.with_name(dll.name + ".orig")
    if not dll.is_file():
        raise DaocError(f"{dll} not found")

    if orig.is_file():
        pristine = orig
    else:
        current = dll.read_bytes()
        if any(_is_patched(current, spec) for spec in proven.values()):
            _say(f"{dll.name} looks already patched and no pristine copy exists; "
                 "leaving it as-is")
            return False
        pristine = dll
    actual = sha256(pristine)
    spec = proven.get(actual)
    if spec is None:
        raise DaocError(f"{pristine.name} sha256 {actual} is not a Proven build; "
                        "refusing to patch an unknown base", 2)

    data = bytearray(pristine.read_bytes())
    done = _apply(data, spec)
    if pristine is dll:
        shutil.copy2(dll, orig)
        _say(f"saved pristine copy -> {orig.name}")
    elif dll.read_bytes() == data:
        _say(f"{dll.name} already patched")
        return False
    for line in done:
        _say(line)
    dll.write_bytes(data)
    _say(f"patched -> {dll}")
    return True
