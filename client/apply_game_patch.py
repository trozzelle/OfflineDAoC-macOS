#!/usr/bin/env python3
"""Apply the connect.exe-equivalent no-encryption patch to game.dll.

Patches (see the upstream analysis in the porting notes):
  - NOP 10 bytes at file offset 0x11035  (kills `mov dword [0x10477ac], 3`)
  - set byte at file offset 0x1102b to 0x01  (state immediate 2 -> 1)

Usage: apply_game_patch.py <path-to-game.dll>

The pristine DLL is kept next to the target as game.dll.orig (created on first
run). The input is verified against the pinned pristine hash before patching, so
a wrong or already-patched base is refused instead of silently corrupted.
"""
import hashlib
import shutil
import sys
from pathlib import Path

# Pristine v0.35b Sluaghbinder client (matches the release's own hash guard).
PRISTINE_SHA256 = "e1d471bb19108610ab9c8ca77dd41af40afe716685b03f4cdeda88c05678463b"

NOP_OFFSET = 0x11035
IMM_OFFSET = 0x1102B
ORIGINAL_BYTES_AT_NOP = bytes.fromhex("c705ac77040103000000")  # mov dword [0x10477ac], 3
ORIGINAL_IMM = 0x02


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    dll = Path(sys.argv[1]).resolve()
    orig = dll.with_name(dll.name + ".orig")
    if not dll.exists():
        print(f"ERROR: {dll} not found")
        return 1

    if not orig.exists():
        actual = sha256(dll)
        already = False
        with dll.open("rb") as f:
            f.seek(NOP_OFFSET)
            nop_bytes = f.read(10)
            f.seek(IMM_OFFSET)
            imm_byte = f.read(1)[0]
        if nop_bytes == b"\x90" * 10 or imm_byte == 0x01:
            already = True
        if already:
            print("ERROR: game.dll looks already patched and no pristine copy exists; "
                  "refusing to treat it as pristine. Restore the original first.")
            return 1
        if actual != PRISTINE_SHA256:
            print(f"ERROR: game.dll hash mismatch — not the pinned pristine client")
            print(f"  expected {PRISTINE_SHA256}")
            print(f"  actual   {actual}")
            print("Refusing to patch an unknown base.")
            return 1
        shutil.copy2(dll, orig)
        print(f"Saved pristine copy -> {orig.name}")

    data = bytearray(orig.read_bytes())

    if data[NOP_OFFSET:NOP_OFFSET + 10] != ORIGINAL_BYTES_AT_NOP:
        if data[NOP_OFFSET:NOP_OFFSET + 10] == b"\x90" * 10:
            print("NOP region already patched.")
        else:
            print(f"ERROR: unexpected bytes at 0x{NOP_OFFSET:x}: "
                  f"{bytes(data[NOP_OFFSET:NOP_OFFSET + 10]).hex(' ')}")
            return 1
    else:
        data[NOP_OFFSET:NOP_OFFSET + 10] = b"\x90" * 10
        print(f"NOPed 10 bytes at 0x{NOP_OFFSET:x}")

    if data[IMM_OFFSET] == ORIGINAL_IMM:
        data[IMM_OFFSET] = 0x01
        print(f"State immediate at 0x{IMM_OFFSET:x}: 0x{ORIGINAL_IMM:02x} -> 0x01")
    elif data[IMM_OFFSET] == 0x01:
        print("State immediate already 0x01.")
    else:
        print(f"ERROR: unexpected immediate at 0x{IMM_OFFSET:x}: 0x{data[IMM_OFFSET]:02x}")
        return 1

    dll.write_bytes(data)
    print(f"Patched -> {dll}")
    return 0


if __name__ == "__main__":
    sys.exit(main())