"""
Blowfish ECB cipher for Lineage 2 Login/Game Server packets.

L2 uses a non-standard Blowfish variant where each 4-byte word within an
8-byte block is processed in LITTLE-ENDIAN order (LSB first), matching the
L2Net/L2J BlowfishEngine implementation. PyCryptodome uses standard big-endian
Blowfish, so we swap bytes within each 4-byte word before and after each
encrypt/decrypt call to achieve the correct LE behaviour.

Default key for Interlude (CT2.4): 6B60CB5B82CE90B1CC2B6C556C6C6C6C
"""
from Crypto.Cipher import Blowfish

DEFAULT_KEY = bytes.fromhex("6B60CB5B82CE90B1CC2B6C556C6C6C6C")


def _swap_words(data: bytes) -> bytes:
    """Byte-reverse each 4-byte word (LE ↔ BE conversion within each word)."""
    b = bytearray(data)
    for i in range(0, len(b) - 3, 4):
        b[i], b[i+3] = b[i+3], b[i]
        b[i+1], b[i+2] = b[i+2], b[i+1]
    return bytes(b)


class BlowfishCipher:
    def __init__(self, key: bytes = DEFAULT_KEY):
        self._key = key
        self._make_cipher()

    def _make_cipher(self):
        self._cipher = Blowfish.new(self._key, Blowfish.MODE_ECB)

    def update_key(self, key: bytes) -> None:
        self._key = key
        self._make_cipher()

    @property
    def key(self) -> bytes:
        return self._key

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data with L2 little-endian Blowfish."""
        data = _pad(data)
        self._make_cipher()
        return _swap_words(self._cipher.encrypt(_swap_words(data)))

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data with L2 little-endian Blowfish."""
        if len(data) % 8 != 0:
            raise ValueError(f"Blowfish decrypt: data length {len(data)} not multiple of 8")
        self._make_cipher()
        return _swap_words(self._cipher.decrypt(_swap_words(data)))


def _pad(data: bytes) -> bytes:
    """Pad to 8-byte boundary with null bytes."""
    remainder = len(data) % 8
    if remainder:
        data += b"\x00" * (8 - remainder)
    return data
