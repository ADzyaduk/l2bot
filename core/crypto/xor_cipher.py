"""
XOR cipher layers for Lineage 2.

Two types:
1. Simple XOR — for older chronicles (C1-C3) on the game server.
2. NewCrypt XOR Pass — used by the Login Server on ALL encrypted packets
   (applied after Blowfish decrypt / before Blowfish encrypt).
   Algorithm taken directly from L2Net/Code/Crypting/NewCrypt.cs.
"""
import struct


class XorCipher:
    """Simple additive XOR — game server, old chronicles."""

    def __init__(self, key: int = 0):
        self._key = key

    def update_key(self, key: int) -> None:
        self._key = key

    def decrypt(self, data: bytes) -> bytes:
        key = self._key
        result = bytearray(len(data))
        for i, b in enumerate(data):
            result[i] = b ^ ((key >> (8 * (i % 4))) & 0xFF)
        return bytes(result)

    def encrypt(self, data: bytes) -> bytes:
        return self.decrypt(data)  # XOR is symmetric


class L2GameCrypt:
    """
    L2J Interlude Game Server XOR cipher.

    Used for game server ↔ client packets (NOT login server).
    Each direction has its own evolving key state.

    Algorithm from L2JServer GameCrypt.java (Interlude/C4-C6):
      decrypt: each byte XORed with key[i%4] and previous RAW byte
      encrypt: each byte XORed with key[i%4] and previous CIPHER byte
      after each block: key[8..11] += block_size
    """

    def __init__(self, key: bytes):
        self._key = bytearray(key[:16].ljust(16, b'\x00'))

    def decrypt(self, data: bytes) -> bytes:
        buf = bytearray(data)
        prev = 0
        for i in range(len(buf)):
            raw = buf[i]
            buf[i] = raw ^ self._key[i & 15] ^ prev
            prev = raw
        # evolve key counter (bytes 8-11)
        size = len(data)
        old = int.from_bytes(self._key[8:12], 'little')
        self._key[8:12] = ((old + size) & 0xFFFFFFFF).to_bytes(4, 'little')
        return bytes(buf)

    def encrypt(self, data: bytes) -> bytes:
        buf = bytearray(data)
        prev = 0
        for i in range(len(buf)):
            enc = buf[i] ^ self._key[i & 15] ^ prev
            buf[i] = enc
            prev = enc
        # evolve key counter (bytes 8-11)
        size = len(data)
        old = int.from_bytes(self._key[8:12], 'little')
        self._key[8:12] = ((old + size) & 0xFFFFFFFF).to_bytes(4, 'little')
        return bytes(buf)


# ------------------------------------------------------------------ #
# Login Server NewCrypt — matches NewCrypt.cs from L2Net exactly
# ------------------------------------------------------------------ #

def login_dec_xor_pass(raw: bytearray, offset: int, size: int, key: int) -> None:
    """
    Decrypt XOR pass — applied to Login Server packets AFTER Blowfish decrypt.
    Modifies raw in-place.

    Port of NewCrypt.decXORPass() from L2Net/Code/Crypting/NewCrypt.cs.
    The key is read from raw[size-8 : size-4] by the caller before calling this.
    """
    stop = 4 + offset
    pos = size - 12
    ecx = key & 0xFFFFFFFF

    while stop <= pos:
        edx = struct.unpack_from("<I", raw, pos)[0]
        edx = (edx ^ ecx) & 0xFFFFFFFF
        ecx = (ecx - edx) & 0xFFFFFFFF
        struct.pack_into("<I", raw, pos, edx)
        pos -= 4


def login_enc_xor_pass(raw: bytearray, offset: int, size: int, key: int) -> None:
    """
    Encrypt XOR pass — applied BEFORE Blowfish encrypt on outbound Login packets.
    Writes the accumulated key into the last 4 bytes of the range.

    Port of NewCrypt.encXORPass() from L2Net/Code/Crypting/NewCrypt.cs.
    """
    stop = size - 8
    pos = 4 + offset
    ecx = key & 0xFFFFFFFF

    while pos < stop:
        edx = struct.unpack_from("<I", raw, pos)[0]
        ecx = (ecx + edx) & 0xFFFFFFFF
        edx = (edx ^ ecx) & 0xFFFFFFFF
        struct.pack_into("<I", raw, pos, edx)
        pos += 4

    struct.pack_into("<I", raw, pos, ecx)


def login_append_checksum(raw: bytearray, offset: int, size: int) -> None:
    """
    Append XOR checksum to Login Server outbound packet body.
    Port of NewCrypt.appendChecksum() from L2Net/Code/Crypting/NewCrypt.cs.
    """
    chksum = 0
    count = size - 4
    i = offset
    while i < count:
        chksum ^= struct.unpack_from("<I", raw, i)[0]
        i += 4
    struct.pack_into("<I", raw, i, chksum & 0xFFFFFFFF)


def login_verify_checksum(raw: bytes, offset: int, size: int) -> bool:
    """Verify XOR checksum of a Login Server packet body."""
    if (size & 3) != 0 or size <= 4:
        return False
    chksum = 0
    count = size - 4
    i = offset
    while i < count:
        chksum ^= struct.unpack_from("<I", raw, i)[0]
        i += 4
    stored = struct.unpack_from("<I", raw, i)[0]
    return stored == chksum
