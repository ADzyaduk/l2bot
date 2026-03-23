"""
Lineage 2 packet checksum.

Algorithm: XOR of all 4-byte little-endian words in the data.
The checksum is appended as 4 bytes (LE) at the end of the packet body
before Blowfish encryption. On receive it must be verified.

Login server also uses a checksum but with a different layout — handled
separately in login_proxy.py (the checksum covers different byte ranges).
"""
import struct


def compute(data: bytes) -> int:
    """Return the L2 checksum integer for *data* (4-byte aligned, any length)."""
    result = 0
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        if len(chunk) < 4:
            chunk = chunk + b"\x00" * (4 - len(chunk))
        result ^= struct.unpack_from("<I", chunk)[0]
    return result


def verify(data: bytes) -> bool:
    """
    Verify checksum embedded in *data*.

    L2 game packets (after Blowfish decrypt):
      last 4 bytes = checksum over all preceding bytes (including null padding).
      Total block is a multiple of 8 bytes.
    Returns True if valid.
    """
    if len(data) < 4:
        return False
    payload = data[:-4]
    stored = struct.unpack_from("<I", data, len(data) - 4)[0]
    return compute(payload) == stored


def append(data: bytes) -> bytes:
    """
    Pad *data* so that (data + 4-byte checksum) is a multiple of 8,
    then append the checksum.

    The checksum covers all bytes INCLUDING the null padding.
    Result length is always a multiple of 8 — ready for Blowfish ECB.
    """
    # Determine how many null bytes to insert before the 4-byte checksum
    # so that total = len(data) + padding + 4  is divisible by 8
    total_target = ((len(data) + 4 + 7) // 8) * 8
    padding = total_target - len(data) - 4
    padded = data + b"\x00" * padding
    chk = compute(padded)
    return padded + struct.pack("<I", chk)
