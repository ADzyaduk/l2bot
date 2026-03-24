"""Login ServerList patch: logical length, stride, checksum, padding."""
from __future__ import annotations

import struct

from core.crypto.xor_cipher import login_append_checksum
from core.proxy.login_proxy import _login_logical_body_len


def _build_server_list_23b(*, count: int = 3) -> bytes:
    """Interlude-style list with 23-byte rows (16 + 7 extra), + XOR chk + BF pad to 80."""
    buf = bytearray()
    buf.append(0x04)
    buf.append(count)
    buf.append(0)
    for i in range(count):
        buf.append(i + 1)
        buf.extend([51, 38, 238, 76])
        buf.extend(struct.pack("<I", 7777))
        buf.append(18)
        buf.append(0)
        buf.extend(struct.pack("<HH", 0, 1000))
        buf.append(0)
        buf.extend(b"\x00" * 7)
    assert len(buf) == 3 + count * 23
    logical = bytearray(len(buf) + 4)
    logical[: len(buf)] = buf
    login_append_checksum(logical, 0, len(logical))
    pad = (8 - (len(logical) % 8)) % 8
    return bytes(logical) + b"\x00" * pad


def test_login_logical_len_strips_bf_padding() -> None:
    body = _build_server_list_23b()
    assert len(body) == 80
    logical = _login_logical_body_len(body)
    assert logical == 76
    assert body[logical:] == b"\x00\x00\x00\x00"


def test_stride_23_all_ips_patched() -> None:
    from core.proxy.session import LoginSession
    from core.proxy.login_proxy import _LoginRelayProtocol

    body = _build_server_list_23b()
    session = LoginSession(listen_game_port=17777)
    proto = _LoginRelayProtocol(None, session, "s2c")
    out = proto._intercept_server(0x04, body)
    assert out is not None
    assert len(out) == len(body)
    logical = _login_logical_body_len(out)
    pos = 3
    stride = 23
    for _ in range(3):
        assert out[pos + 1 : pos + 5] == b"\x7f\x00\x00\x01"
        assert struct.unpack_from("<I", out, pos + 5)[0] == 17777
        pos += stride
