"""
Base packet class providing cursor-based binary read/write helpers.

All L2 strings are null-terminated UTF-16LE.
Integers are little-endian.

Usage:
    # Reading (server → client)
    pkt = BasePacket(raw_bytes)
    x = pkt.read_int()
    name = pkt.read_string()

    # Writing (client → server)
    pkt = BasePacket()
    pkt.write_byte(opcode)
    pkt.write_int(x)
    pkt.write_string(name)
    raw = pkt.to_bytes()
"""
import struct


class BasePacket:
    def __init__(self, data: bytes = b""):
        self._buf = bytearray(data)
        self._pos = 0  # read cursor

    # ------------------------------------------------------------------ #
    # Read helpers
    # ------------------------------------------------------------------ #

    def read_byte(self) -> int:
        v = self._buf[self._pos]
        self._pos += 1
        return v

    def read_short(self) -> int:
        v = struct.unpack_from("<h", self._buf, self._pos)[0]
        self._pos += 2
        return v

    def read_ushort(self) -> int:
        v = struct.unpack_from("<H", self._buf, self._pos)[0]
        self._pos += 2
        return v

    def read_int(self) -> int:
        v = struct.unpack_from("<i", self._buf, self._pos)[0]
        self._pos += 4
        return v

    def read_uint(self) -> int:
        v = struct.unpack_from("<I", self._buf, self._pos)[0]
        self._pos += 4
        return v

    def read_long(self) -> int:
        v = struct.unpack_from("<q", self._buf, self._pos)[0]
        self._pos += 8
        return v

    def read_ulong(self) -> int:
        v = struct.unpack_from("<Q", self._buf, self._pos)[0]
        self._pos += 8
        return v

    def read_float(self) -> float:
        v = struct.unpack_from("<f", self._buf, self._pos)[0]
        self._pos += 4
        return v

    def read_double(self) -> float:
        v = struct.unpack_from("<d", self._buf, self._pos)[0]
        self._pos += 8
        return v

    def read_bytes(self, n: int) -> bytes:
        v = bytes(self._buf[self._pos:self._pos + n])
        self._pos += n
        return v

    def read_string(self) -> str:
        """Read null-terminated UTF-16LE string."""
        start = self._pos
        while self._pos + 1 < len(self._buf):
            if self._buf[self._pos] == 0 and self._buf[self._pos + 1] == 0:
                s = self._buf[start:self._pos].decode("utf-16-le", errors="replace")
                self._pos += 2  # consume null terminator
                return s
            self._pos += 2
        # no null found — consume to end
        s = self._buf[start:self._pos].decode("utf-16-le", errors="replace")
        return s

    def remaining(self) -> int:
        return len(self._buf) - self._pos

    def peek_byte(self) -> int:
        return self._buf[self._pos]

    # ------------------------------------------------------------------ #
    # Write helpers
    # ------------------------------------------------------------------ #

    def write_byte(self, v: int) -> None:
        self._buf.append(v & 0xFF)

    def write_short(self, v: int) -> None:
        self._buf += struct.pack("<h", v)

    def write_ushort(self, v: int) -> None:
        self._buf += struct.pack("<H", v)

    def write_int(self, v: int) -> None:
        self._buf += struct.pack("<i", v)

    def write_uint(self, v: int) -> None:
        self._buf += struct.pack("<I", v)

    def write_long(self, v: int) -> None:
        self._buf += struct.pack("<q", v)

    def write_ulong(self, v: int) -> None:
        self._buf += struct.pack("<Q", v)

    def write_float(self, v: float) -> None:
        self._buf += struct.pack("<f", v)

    def write_double(self, v: float) -> None:
        self._buf += struct.pack("<d", v)

    def write_bytes(self, data: bytes) -> None:
        self._buf += data

    def write_string(self, s: str) -> None:
        """Write null-terminated UTF-16LE string."""
        self._buf += s.encode("utf-16-le") + b"\x00\x00"

    def to_bytes(self) -> bytes:
        return bytes(self._buf)

    def __len__(self) -> int:
        return len(self._buf)
