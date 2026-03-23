"""
Builds outbound L2 packets, adds checksum, encrypts, and frames them.

Frame format:
  [2 bytes LE: total_length] [encrypted_body]

Encrypted body before encryption:
  [1 byte: opcode] [payload...] [4 bytes: checksum]  (padded to 8-byte boundary)
"""
import struct
import logging

from core.crypto.blowfish_cipher import BlowfishCipher
from core.crypto.checksum import append as append_checksum

log = logging.getLogger(__name__)


def build_packet(opcode: int, payload: bytes, cipher: BlowfishCipher | None) -> bytes:
    """
    Build a complete framed and encrypted L2 game packet.

    Parameters
    ----------
    opcode  : 1-byte opcode
    payload : raw payload bytes (without opcode and checksum)
    cipher  : active Blowfish cipher; if None, body is sent unencrypted
    """
    body = bytes([opcode]) + payload
    body = append_checksum(body)  # append 4-byte XOR checksum

    if cipher:
        body = cipher.encrypt(body)  # pads to 8-byte boundary internally

    total_len = len(body) + 2  # +2 for the length field itself
    return struct.pack("<H", total_len) + body


def build_login_packet(payload: bytes) -> bytes:
    """
    Build a Login Server packet (different framing, no Blowfish).

    Login packets: [2 bytes LE: total_length] [raw_payload]
    """
    total_len = len(payload) + 2
    return struct.pack("<H", total_len) + payload
