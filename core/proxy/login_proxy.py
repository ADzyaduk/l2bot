"""
Login Server MITM Proxy.

Architecture:
  L2 Client --[TCP localhost:2106]--> LoginProxy --[TCP real_host:2106]--> Real Login Server

What we do:
1. Client connects to us on port 2106.
2. We connect to the real Login Server.
3. We relay all packets transparently in both directions.
4. We intercept key packets to extract RSA key, Blowfish key, and auth tokens.

Login Server packet framing (different from Game Server):
  [2 bytes LE: total_length] [raw payload — NOT Blowfish encrypted]
  Payload[0] = opcode

The Login Server does use its own obfuscation on the Init packet, but the
Blowfish key it sends is embedded in plaintext within the Init body.
"""
import asyncio
import logging
import struct
from typing import Callable

from core.crypto.blowfish_cipher import BlowfishCipher
from core.crypto.xor_cipher import (
    login_append_checksum,
    login_dec_xor_pass,
    login_enc_xor_pass,
    login_verify_checksum,
)
from core.proxy.session import LoginSession

log = logging.getLogger(__name__)


def _login_logical_body_len(body: bytes) -> int:
    """
    Blowfish-decrypted login payloads are padded with trailing 0x00 to a multiple
    of 8. The XOR checksum ends the *logical* packet; padding dwords after it can
    still satisfy verify(len(body)) spuriously, so we take the smallest end where
    verify passes and either we consumed the whole buffer or only 0x00 remains.
    """
    n = len(body)
    candidates: list[int] = []
    for end in range(8, n + 1, 4):
        if not login_verify_checksum(body, 0, end):
            continue
        tail = body[end:]
        if end < n and any(tail):
            continue
        candidates.append(end)
    return min(candidates) if candidates else n


def _reset_login_session_for_new_client(session: LoginSession) -> None:
    """Each new TCP connection from L2 client must start clean (new BF key from Init)."""
    session.login_cipher = None
    session.server_rsa_modulus = b""
    session.server_blowfish_key = b""
    session.login_ok1 = 0
    session.login_ok2 = 0
    session.play_ok1 = 0
    session.play_ok2 = 0
    session.game_host = ""
    session.game_port = 7777


# Login Server opcodes (server → client)
LS_INIT          = 0x00
LS_SERVER_LIST   = 0x04
LS_PLAY_OK       = 0x07
LS_LOGIN_FAIL    = 0x01
LS_PLAY_FAIL     = 0x06
LS_GG_AUTH       = 0x0B

# Login Server opcodes (client → server)
LC_REQUEST_GG    = 0x07
LC_AUTH_LOGIN    = 0x00
LC_REQUEST_SERVERS = 0x05
LC_REQUEST_CHAR_COUNTS = 0x06
LC_REQUEST_PLAY  = 0x02


class _LoginRelayProtocol(asyncio.Protocol):
    """One side of the relay (either client-facing or server-facing)."""

    def __init__(self, peer: "_LoginRelayProtocol | None", session: LoginSession,
                 direction: str, on_packet_cb: Callable | None = None):
        self._peer = peer
        self._session = session
        self._direction = direction  # "c2s" or "s2c"
        self._on_packet_cb = on_packet_cb  # called with (opcode, raw_body)
        self._transport: asyncio.Transport | None = None
        self._buf = bytearray()

    def set_peer(self, peer: "_LoginRelayProtocol") -> None:
        self._peer = peer

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._transport = transport

    def data_received(self, data: bytes) -> None:
        self._buf += data
        self._process()

    def _process(self) -> None:
        while len(self._buf) >= 2:
            total_len = struct.unpack_from("<H", self._buf, 0)[0]
            if total_len < 2:
                self._buf = self._buf[1:]
                continue
            if len(self._buf) < total_len:
                break
            raw = bytes(self._buf[:total_len])
            self._buf = self._buf[total_len:]

            body = raw[2:]  # strip length header

            # Login Server: Init packet (opcode 0x00) is always PLAINTEXT.
            # Every packet after Init is Blowfish-encrypted with the key from Init.
            # We decrypt s2c packets to read the real opcode and intercept ServerList.
            cipher: BlowfishCipher | None = self._session.login_cipher
            is_encrypted = (self._direction == "s2c" and cipher is not None and len(body) % 8 == 0)

            if is_encrypted:
                try:
                    plain = cipher.decrypt(body)
                    real_opcode = plain[0]
                except Exception as exc:
                    log.warning("[Login s2c] decrypt failed: %s — forwarding raw", exc)
                    plain = body
                    real_opcode = body[0] if body else 0xFF
            else:
                plain = body
                real_opcode = body[0] if body else 0xFF

            log.info("[Login %s] opcode=0x%02X (raw_first=0x%02X) len=%d",
                     self._direction, real_opcode, body[0] if body else 0xFF, total_len)

            # Intercept — may return a modified PLAINTEXT body
            modified_plain: bytes | None = None
            if self._direction == "s2c":
                modified_plain = self._intercept_server(real_opcode, plain)
            else:
                self._intercept_client(real_opcode, plain)

            # Build the outbound packet
            if self._peer and self._peer._transport:
                if modified_plain is not None:
                    # Re-encrypt with the same login cipher
                    if is_encrypted and cipher:
                        new_body = cipher.encrypt(modified_plain)
                    else:
                        new_body = modified_plain
                    out = struct.pack("<H", len(new_body) + 2) + new_body
                    self._peer._transport.write(out)
                else:
                    self._peer._transport.write(raw)  # forward original unchanged

            if self._on_packet_cb:
                self._on_packet_cb(real_opcode, modified_plain or plain)

    def _intercept_server(self, opcode: int, body: bytes) -> bytes | None:
        """
        Intercept server packets. Returns modified body bytes if the packet
        was altered (so caller sends the modified version), or None if unchanged.
        """
        if opcode == LS_INIT:
            if len(body) >= 1 + 4 + 4 + 128:
                rsa_start = 9
                self._session.server_rsa_modulus = body[rsa_start: rsa_start + 128]
                bf_start = rsa_start + 128 + 16
                if len(body) >= bf_start + 16:
                    key = body[bf_start: bf_start + 16]
                    self._session.server_blowfish_key = key
                    self._session.login_cipher = BlowfishCipher(key)
                    log.info("[LoginProxy] Captured Login BF key: %s → cipher ready", key.hex())
                else:
                    # Fallback: use default key (many private servers never change it)
                    from core.crypto.blowfish_cipher import DEFAULT_KEY
                    self._session.login_cipher = BlowfishCipher(DEFAULT_KEY)
                    log.info("[LoginProxy] BF key not in Init — using default key")
            log.info("[LoginProxy] Init intercepted, body_len=%d", len(body))
            return None  # forward unchanged

        elif opcode == LS_LOGIN_FAIL:
            reason = body[1] if len(body) > 1 else 0xFF
            reasons = {
                0x01: "System error", 0x02: "Invalid password", 0x03: "Invalid login",
                0x04: "Access failed", 0x05: "Account in use", 0x07: "Account banned",
                0x09: "Server is full", 0x0F: "Subscriptions expired",
            }
            log.warning("[LoginProxy] LOGIN FAILED — reason: %s (0x%02X)",
                        reasons.get(reason, "Unknown"), reason)
            return None

        elif opcode == LS_PLAY_FAIL:
            log.warning("[LoginProxy] PLAY FAILED (server rejected game entry)")
            return None

        elif opcode == LS_GG_AUTH:
            log.info("[LoginProxy] GGAuth received from server (GameGuard OK)")
            return None

        elif opcode == 0x03:  # LoginOk / AccountKicked depending on chronicle
            log.info("[LoginProxy] LoginOk / session token received")
            return None

        elif opcode == LS_PLAY_OK:
            if len(body) >= 9:
                self._session.play_ok1 = struct.unpack_from("<I", body, 1)[0]
                self._session.play_ok2 = struct.unpack_from("<I", body, 5)[0]
                log.info("[LoginProxy] PlayOk captured: %d / %d",
                         self._session.play_ok1, self._session.play_ok2)
            return None

        elif opcode == LS_SERVER_LIST:
            # Parse real server IPs, store them, then PATCH the packet
            # replacing each real game server IP with 127.0.0.1 so the client
            # connects to our GameProxy instead of the real server directly.
            #
            # Base entry: id(1) ip(4) port(4) age(1) pvp(1) online(2) max(2) status(1) = 16 B.
            # Many L2J forks append extra fields per server (typ. 23 B total); infer stride
            # from (logical_len - header - checksum) // count after stripping BF padding.
            # Skip rows with invalid TCP port (placeholders); continue so other slots still patch.
            if len(body) > 3:
                logical_len = _login_logical_body_len(body)
                pad_suffix = body[logical_len:]
                if len(pad_suffix):
                    log.debug(
                        "[LoginProxy] ServerList: stripped %d Blowfish pad byte(s), logical_len=%d",
                        len(pad_suffix),
                        logical_len,
                    )
                count = body[1]
                log.info("[LoginProxy] Server list: advertised count=%d", count)
                pos = 3  # skip opcode(1) + count(1) + last_server(1)
                patched = bytearray(body[:logical_len])
                chk_start = len(patched) - 4  # first byte of XOR checksum (exclusive end for entries)
                patched_any = False

                payload_for_stride = chk_start - pos
                stride = 16
                if count > 0 and payload_for_stride > 0 and payload_for_stride % count == 0:
                    stride = payload_for_stride // count
                if stride < 9:
                    stride = 16
                log.debug("[LoginProxy] ServerList: entry stride=%d bytes", stride)

                for idx in range(count):
                    if pos + stride > chk_start:
                        log.warning(
                            "[LoginProxy] ServerList: entry %d overflows packet (pos=%d, chk_start=%d)",
                            idx, pos, chk_start,
                        )
                        break
                    svr_id = patched[pos]
                    ip_bytes = bytes(patched[pos + 1: pos + 5])
                    port = struct.unpack_from("<I", patched, pos + 5)[0]
                    ip = ".".join(str(b) for b in ip_bytes)

                    if not (1 <= port <= 65535):
                        log.warning(
                            "[LoginProxy] ServerList: skip bogus entry %d at pos %d (%s:%s)",
                            idx, pos, ip, port,
                        )
                        pos += stride
                        continue

                    log.info(
                        "[LoginProxy] Server %d: %s:%d → redirecting to 127.0.0.1:%d",
                        svr_id, ip, port, self._session.listen_game_port,
                    )

                    if not self._session.game_host:
                        self._session.game_host = ip
                        self._session.game_port = port
                        if self._session.on_game_server_discovered:
                            self._session.on_game_server_discovered(ip, port)

                    patched[pos + 1: pos + 5] = b"\x7f\x00\x00\x01"
                    struct.pack_into("<I", patched, pos + 5, self._session.listen_game_port)
                    patched_any = True
                    pos += stride

                if patched_any:
                    if len(patched) >= 8:
                        login_append_checksum(patched, 0, len(patched))
                    out = bytes(patched) + pad_suffix
                    if len(out) != len(body):
                        log.warning(
                            "[LoginProxy] ServerList: patched len %d != original %d — forwarding raw",
                            len(out),
                            len(body),
                        )
                        return None
                    log.info("[LoginProxy] ServerList patched — client will connect to our GameProxy")
                    return out
                log.warning("[LoginProxy] ServerList: no valid entries patched — forwarding unchanged")
                return None

        return None

    def _intercept_client(self, opcode: int, body: bytes) -> None:
        if opcode == LC_AUTH_LOGIN:
            log.info("[LoginProxy] Client sent AuthLogin (credentials encrypted)")
        elif opcode == LC_REQUEST_GG:
            log.info("[LoginProxy] Client sent RequestGG (GameGuard)")
        elif opcode == LC_REQUEST_SERVERS:
            log.info("[LoginProxy] Client requested server list")
        elif opcode == LC_REQUEST_CHAR_COUNTS:
            log.info("[LoginProxy] Client requested char counts")
        elif opcode == LC_REQUEST_PLAY:
            if len(body) >= 3:
                svr_id = struct.unpack_from("<H", body, 1)[0]
                log.info("[LoginProxy] Client selected server ID=%d", svr_id)
        else:
            log.info("[LoginProxy] Unknown client opcode 0x%02X len=%d", opcode, len(body))

    def connection_lost(self, exc: Exception | None) -> None:
        log.info("[Login %s] Connection lost: %s", self._direction, exc)
        if self._peer and self._peer._transport:
            self._peer._transport.close()


class LoginProxyServer:
    """
    Listens for L2 clients on localhost:2106 and proxies to the real login server.
    """

    def __init__(self, real_host: str, real_port: int = 2106,
                 listen_port: int = 2106, session: LoginSession | None = None):
        self.real_host = real_host
        self.real_port = real_port
        self.listen_port = listen_port
        self.session = session or LoginSession()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._server = await loop.create_server(
            self._client_connected,
            host="127.0.0.1",
            port=self.listen_port,
        )
        log.info("[LoginProxy] Listening on 127.0.0.1:%d → %s:%d",
                 self.listen_port, self.real_host, self.real_port)

    def _client_connected(self) -> asyncio.Protocol:
        """Factory: called by asyncio when a new client connects."""
        _reset_login_session_for_new_client(self.session)
        c2s = _LoginRelayProtocol(None, self.session, "c2s")
        s2c = _LoginRelayProtocol(None, self.session, "s2c")

        async def _connect_to_server():
            loop = asyncio.get_running_loop()
            try:
                _, s2c_proto = await loop.create_connection(
                    lambda: s2c,
                    host=self.real_host,
                    port=self.real_port,
                )
                c2s.set_peer(s2c)
                s2c.set_peer(c2s)
                log.info("[LoginProxy] Connected to real login server %s:%d",
                         self.real_host, self.real_port)
            except Exception as exc:
                log.error("[LoginProxy] Failed to connect to real server: %s", exc)
                if c2s._transport:
                    c2s._transport.close()

        asyncio.ensure_future(_connect_to_server())
        return c2s

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
