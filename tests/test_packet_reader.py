"""Unit tests for BasePacket and packet_writer."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import struct
import pytest
from core.protocol.base_packet import BasePacket
from core.protocol.packet_writer import build_packet
from core.crypto.blowfish_cipher import BlowfishCipher
from core.crypto.checksum import verify


class TestBasePacket:
    def test_int_roundtrip(self):
        p = BasePacket()
        p.write_int(-42)
        p.write_int(999999)
        r = BasePacket(p.to_bytes())
        assert r.read_int() == -42
        assert r.read_int() == 999999

    def test_string_utf16(self):
        p = BasePacket()
        p.write_string("Привет мир")
        r = BasePacket(p.to_bytes())
        assert r.read_string() == "Привет мир"

    def test_all_types(self):
        p = BasePacket()
        p.write_byte(0xAB)
        p.write_short(-100)
        p.write_ushort(60000)
        p.write_int(-1000000)
        p.write_long(9999999999)
        p.write_float(3.14)
        p.write_bytes(b"\xDE\xAD")
        raw = p.to_bytes()
        r = BasePacket(raw)
        assert r.read_byte() == 0xAB
        assert r.read_short() == -100
        assert r.read_ushort() == 60000
        assert r.read_int() == -1000000
        assert r.read_long() == 9999999999
        val = r.read_float()
        assert abs(val - 3.14) < 0.001
        assert r.read_bytes(2) == b"\xDE\xAD"

    def test_empty_string(self):
        p = BasePacket()
        p.write_string("")
        r = BasePacket(p.to_bytes())
        assert r.read_string() == ""


class TestPacketWriter:
    def test_build_framing(self):
        cipher = BlowfishCipher()
        raw = build_packet(0x0F, b"\x01\x02\x03\x04", cipher)
        # First 2 bytes = total length
        total_len = struct.unpack_from("<H", raw, 0)[0]
        assert total_len == len(raw)

    def test_build_decrypt_roundtrip(self):
        cipher = BlowfishCipher()
        payload = b"\x01\x00\x00\x00"  # int = 1
        raw = build_packet(0x0A, payload, cipher)
        # Strip frame
        body_encrypted = raw[2:]
        decrypted = cipher.decrypt(body_encrypted)
        assert decrypted[0] == 0x0A  # opcode
        assert decrypted[1:5] == payload
        # Checksum at end should be valid
        assert verify(decrypted)
