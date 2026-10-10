#!/usr/bin/env python3
"""Apply the connect.exe-equivalent no-encryption patch to game.dll.

Patches (see the upstream analysis in the porting notes):
  - NOP 10 bytes at file offset 0x11035  (kills `mov dword [0x10477ac], 3`)
  - set byte at file offset 0x1102b to 0x01  (state immediate 2 -> 1)

Usage: apply_game_patch.py <path-to-game.dll> [manifest.json]

The pristine DLL is kept next to the target as game.dll.orig (created on first
run). The expected pristine hash comes from the repo's manifest.json
(client.game_dll_sha256); a missing .orig plus a hash mismatch or an
already-patched base is refused instead of silently corrupted. If the pin is
absent (a post-update re-derivation gap), a game.dll whose bytes match the
patched output is accepted as already patched; anything else is refused.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NOP_OFFSET = 0x11035
IMM_OFFSET = 0x1102B
ORIGINAL_BYTES_AT_NOP = bytes.fromhex("c705ac77040103000000")  # mov dword [0x10477ac], 3
ORIGINAL_IMM = 0x02
PATCHED_BYTES_AT_NOP = b"\x90" * 10
PATCHED_IMM = 0x01


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pristine_pin(manifest_path: Path | None) -> str | None:
    """Expected pristine hash from manifest.json (client.game_dll_sha256)."""
    candidates = [manifest_path] if manifest_path else [REPO / "manifest.json"]
    for cand in candidates:
        try:
            return json.loads(cand.read_text())["client"]["game_dll_sha256"]
        except (OSError, KeyError, ValueError):
            continue
    return None


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    dll = Path(sys.argv[1]).resolve()
    manifest = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else None
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
        if nop_bytes == PATCHED_BYTES_AT_NOP and imm_byte == PATCHED_IMM:
            already = True
        if already:
            print("NOTE: game.dll looks already patched and no pristine copy "
                  "exists; leaving it as-is (nothing to do).")
            return 0
        pin = pristine_pin(manifest)
        if pin is None:
            print("ERROR: no pristine hash pin available (manifest.json lacks "
                  "client.game_dll_sha256) and no .orig exists.")
            print("Re-derive the pin for this client build, then retry.")
            return 1
        if actual != pin:
            print("ERROR: game.dll hash mismatch — not the pinned pristine client")
            print(f"  expected {pin}")
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