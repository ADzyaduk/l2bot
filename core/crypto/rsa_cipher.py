"""
RSA encryption for Lineage 2 Login Server.

The Login Server sends a 128-byte RSA public key modulus in the Init packet.
Credentials are encrypted with this key (exponent 65537) before sending.

L2 applies a proprietary "scramble" to the RSA key block after encryption:
bytes [0x00-0x40] and [0x40-0x80] are swapped, then the lower nibble of
byte[0] and the lower nibble of byte[0x4D] are XORed.
"""
import os
import struct

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5


def scramble_modulus(modulus: bytes) -> bytes:
    """Apply L2's proprietary scramble to the 128-byte RSA modulus."""
    m = bytearray(modulus)
    # swap first and second 64-byte halves
    m[0:0x40], m[0x40:0x80] = m[0x40:0x80], m[0x00:0x40]
    # XOR nibble corrections
    m[0x00] ^= m[0x5D]
    m[0x5D] ^= m[0x00]
    m[0x00] ^= m[0x5D]
    m[0x0D] ^= m[0x48]
    m[0x48] ^= m[0x0D]
    m[0x0D] ^= m[0x48]
    return bytes(m)


def unscramble_modulus(modulus: bytes) -> bytes:
    """Reverse the L2 scramble (same operations are self-inverse)."""
    return scramble_modulus(modulus)


def build_rsa_key(modulus_128: bytes, exponent: int = 65537) -> RSA.RsaKey:
    """Build an RSA key object from the raw 128-byte modulus."""
    n = int.from_bytes(modulus_128, "big")
    e = exponent
    return RSA.construct((n, e))


def encrypt_credentials(username: str, password: str, rsa_key: RSA.RsaKey) -> bytes:
    """
    Encrypt L2 login credentials into a 128-byte block.

    Layout (before RSA encryption):
      [0x00] = 0x00  (padding marker)
      [0x01..0x0E] = username (up to 14 bytes, null-padded)
      [0x0F..0x1C] = password (up to 14 bytes, null-padded)
      rest padded with random bytes
    """
    block = bytearray(128)
    uname = username.encode("ascii")[:14]
    passwd = password.encode("ascii")[:14]
    block[0x01:0x01 + len(uname)] = uname
    block[0x0F:0x0F + len(passwd)] = passwd
    # fill remainder with random bytes (except byte 0 stays 0)
    rand = os.urandom(128 - 0x20)
    block[0x20:] = rand[:len(block) - 0x20]
    cipher = PKCS1_v1_5.new(rsa_key)
    # L2 uses raw RSA (no PKCS padding), so encrypt the raw block
    return pow(int.from_bytes(block, "big"), rsa_key.e, rsa_key.n).to_bytes(128, "big")
