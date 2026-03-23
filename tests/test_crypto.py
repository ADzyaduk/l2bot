"""Unit tests for the crypto layer."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.crypto.blowfish_cipher import BlowfishCipher, DEFAULT_KEY
from core.crypto.checksum import compute, verify, append
from core.crypto.xor_cipher import XorCipher


class TestBlowfish:
    def test_encrypt_decrypt_roundtrip(self):
        bf = BlowfishCipher()
        data = b"ABCDEFGH"  # 8 bytes exactly
        assert bf.decrypt(bf.encrypt(data)) == data

    def test_auto_padding(self):
        bf = BlowfishCipher()
        data = b"Hello"  # 5 bytes — should be padded to 8
        enc = bf.encrypt(data)
        assert len(enc) == 8
        dec = bf.decrypt(enc)
        assert dec[:5] == b"Hello"

    def test_key_update(self):
        import os
        bf = BlowfishCipher()
        new_key = os.urandom(16)
        bf.update_key(new_key)
        data = b"TESTDATA"
        assert bf.decrypt(bf.encrypt(data)) == data

    def test_default_key_matches_interlude(self):
        expected = bytes.fromhex("6B60CB5B82CE90B1CC2B6C556C6C6C6C")
        assert DEFAULT_KEY == expected

    def test_decrypt_wrong_length_raises(self):
        bf = BlowfishCipher()
        with pytest.raises(ValueError):
            bf.decrypt(b"short")  # not multiple of 8


class TestChecksum:
    def test_roundtrip(self):
        data = b"\x01\x00\x00\x00\x02\x00\x00\x00"
        assert verify(append(data))

    def test_compute_xor(self):
        # XOR of 0x00000001 ^ 0x00000002 == 0x00000003
        data = b"\x01\x00\x00\x00\x02\x00\x00\x00"
        assert compute(data) == 3

    def test_tampered_fails(self):
        data = b"\x01\x00\x00\x00\x02\x00\x00\x00"
        packet = bytearray(append(data))
        packet[-1] ^= 0xFF  # corrupt checksum
        assert not verify(bytes(packet))

    def test_too_short(self):
        assert not verify(b"\x01\x02")


class TestXorCipher:
    def test_symmetric(self):
        xor = XorCipher(key=0xDEADBEEF)
        data = b"Hello World!"
        assert xor.decrypt(xor.encrypt(data)) == data
