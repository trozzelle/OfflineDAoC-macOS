"""The Client patch: the connect.exe-equivalent no-encryption patch to game.dll,
plus the one header change Wine on Apple Silicon needs.

Only a Proven build is patched: PROVEN_BUILDS maps the sha256 of a pristine
game.dll to the patch spec proven against it, and any other pristine hash is
refused instead of silently corrupted. The current spec (see the upstream
analysis in the porting notes):
  - NOP 10 bytes at file offset 0x11035 (kills `mov dword [0x10477ac], 3`)
  - set the byte at file offset 0x1102b to 0x01 (state immediate 2 -> 1)
  - clear IMAGE_SCN_MEM_SHARED on the 4-byte `Shared` section (characteristics
    at file offset 0x2ec, 0xd0000040 -> 0xc0000040). The section sits on a 4 KB
    boundary; an arm64 Wine runs on 16 KB host pages and cannot map a shared
    section there, so it refuses the whole image ("Bad EXE format"). Unshared,
    each client process gets its own copy of those 4 bytes; daoc runs one client.

The pristine DLL is kept next to the target as game.dll.orig (created on first
run) and every run patches from it, byte-verified. A game.dll without .orig
whose patched regions all revert to a Proven build is treated as patched by an
older run: its pristine bytes are restored into .orig and the current spec is
applied. Anything else that is not a Proven build is refused.
"""
import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Mapping, NamedTuple, Optional, Tuple

from daoc_cli.errors import DaocError, say
from daoc_cli.files import sha256


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

# v0.35b's `Shared` section header: Characteristics (little-endian) at 0x2ec.
UNSHARED_SECTION = Edit(0x2EC, bytes.fromhex("400000d0"), bytes.fromhex("400000c0"),
                        "`Shared` section not IMAGE_SCN_MEM_SHARED (16 KB pages)")

V0_35B: PatchSpec = NO_ENCRYPTION + (UNSHARED_SECTION,)

# Pristine game.dll sha256 -> the patch proven against that build.
PROVEN_BUILDS: Dict[str, PatchSpec] = {
    # OfflineDAoC v0.35b, the Sluaghbinder client.
    "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b": V0_35B,
}


def _restore_pristine(data: bytes, proven: Mapping[str, PatchSpec]) -> Optional[bytes]:
    """data with every region holding a spec's patched bytes put back to the
    original, when that yields the spec's Proven build; None otherwise (nothing
    was patched, or the result is not Proven)."""
    for digest, spec in proven.items():
        restored = bytearray(data)
        for e in spec:
            end = e.offset + len(e.patched)
            if restored[e.offset:end] == e.patched:
                restored[e.offset:end] = e.original
        if restored != data and hashlib.sha256(restored).hexdigest() == digest:
            return bytes(restored)
    return None


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
        restored = _restore_pristine(dll.read_bytes(), proven)
        if restored is not None:
            orig.write_bytes(restored)
            say(f"{dll.name} was patched without a pristine copy; restored one -> {orig.name}")
            pristine = orig
        else:
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
        say(f"saved pristine copy -> {orig.name}")
    elif dll.read_bytes() == data:
        say(f"{dll.name} already patched")
        return False
    for line in done:
        say(line)
    dll.write_bytes(data)
    say(f"patched -> {dll}")
    return True
