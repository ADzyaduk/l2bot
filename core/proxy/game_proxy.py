"""
Game Server MITM Proxy — the core of the bot.

Architecture:
  L2 Client --[TCP localhost:7777]--> GameProxy --[TCP real_host:7777]--> Real Game Server

Transparent relay: all bytes forwarded unchanged in both directions.
For observation (BotEngine), a shadow Blowfish cipher decrypts a copy of each
server packet.  The session key is extracted from the plaintext BlowfishInit (0x00).

If the server sends CryptInit (0xAE), an additional XOR layer (L2GameCrypt) is
activated for shadow decryption of subsequent packets.

Game Server packet framing:
  [2 bytes LE: total_length] [Blowfish-encrypted body]
  Decrypted body: [1 byte opcode] [payload...] [4 bytes checksum]
"""
import asyncio
import logging
import struct
from typing import Callable, Awaitable

# Logged at INFO without enabling full packet DEBUG (see _handle_client_to_server).
_C2S_INFO_PLAIN_OPCODES = frozenset({
    0x04,  # Action
    0x0A,  # AttackRequest
    0x19,  # RequestItemUse
    0x2F,  # Force attack (Teon)
    0x37,  # RequestTargetCancel
    0x39,  # RequestMagicSkillUse
    0x45,  # RequestActionUse
    0x48,  # RequestGetItem (pickup) — same opcode on some builds
})

from core.crypto.blowfish_cipher import BlowfishCipher, DEFAULT_KEY
from core.crypto.checksum import append as append_checksum, verify as verify_checksum
from core.crypto.xor_cipher import L2GameCrypt
from core.proxy.session import GameSession
from core.protocol.registry import get_server_packet_name, get_client_packet_name
from core.protocol.packet_categories import s2c_category_tag

log = logging.getLogger(__name__)
# High-volume S2C/C2S lines go here so the UI can show them on a separate "Packets" pane.
pktlog = logging.getLogger("l2bot.packets")

# Game Server opcodes relevant to the proxy itself
GS_BLOWFISH_INIT = 0x00   # server sends session Blowfish key
GS_CRYPT_INIT    = 0xAE   # older chronicles: XOR key (not used in Interlude)


def _pack_packet(opcode: int, payload: bytes, cipher: BlowfishCipher) -> bytes:
    """Encrypt and frame a game server packet."""
    body = bytes([opcode]) + payload
    body = append_checksum(body)
    encrypted = cipher.encrypt(body)
    total_len = len(encrypted) + 2
    return struct.pack("<H", total_len) + encrypted


class _GameRelayProtocol(asyncio.Protocol):
    """
    One side of the Game Server relay.

    direction: "c2s" (client to server) or "s2c" (server to client)
    """

    def __init__(self, session: GameSession, direction: str):
        self._session = session
        self._direction = direction
        self._transport: asyncio.Transport | None = None
        self._buf = bytearray()
        self._peer: "_GameRelayProtocol | None" = None
        # Called for every fully-decrypted server packet (opcode, payload)
        self.on_server_packet: Callable[[int, bytes], Awaitable[None]] | None = None

    def set_peer(self, peer: "_GameRelayProtocol") -> None:
        self._peer = peer

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._transport = transport
        peer = transport.get_extra_info("peername")
        log.debug("[GameProxy %s] Connected: %s", self._direction, peer)

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
            body = raw[2:]  # encrypted body

            if self._direction == "s2c":
                self._handle_server_to_client(body)
            else:
                self._handle_client_to_server(body)

    def _decrypt_game_body(self, body: bytes, cipher: BlowfishCipher) -> bytes | None:
        """Decrypt game body, return plaintext or None on error."""
        try:
            plain = cipher.decrypt(body)
        except Exception as exc:
            log.error("[GameProxy] Decrypt error: %s", exc)
            return None
        if not verify_checksum(plain):
            log.debug("[GameProxy] Checksum mismatch (ignored)")
        return plain

    def _handle_server_to_client(self, body: bytes) -> None:
        """Process packet coming from real server, forward to client."""
        sess = self._session

        # ---- Step 1: Always forward transparently ----
        if self._peer and self._peer._transport:
            self._peer._transport.write(struct.pack("<H", len(body) + 2) + body)

        # ---- Step 2: Observe for BotEngine (shadow XOR decryption) ----
        if not sess.crypto_initialized:
            # BlowfishInit arrives as plaintext — intercept to extract key
            if body and body[0] == GS_BLOWFISH_INIT:
                self._handle_blowfish_init(body[1:])
            return

        if not sess.xor_s2c:
            return  # no shadow cipher yet

        # XOR-decrypt a copy of each s2c body for observation
        plain = bytes(sess.xor_s2c.decrypt(body))
        opcode = plain[0] if plain else 0xFF
        payload = plain[1:-4] if len(plain) > 5 else plain[1:]

        name = get_server_packet_name(opcode)
        cat = s2c_category_tag(name)
        tag = f"[{cat}] " if cat else ""
        # Reduce log noise: frequent movement/tick packets → DEBUG
        _quiet_s2c = {0x01, 0x2D, 0x16}
        if opcode in _quiet_s2c:
            pktlog.debug(
                "[S→C]%s0x%02X %s (%d bytes payload)", tag, opcode, name, len(payload),
            )
        else:
            pktlog.info(
                "[S→C]%s0x%02X %s (%d bytes payload)", tag, opcode, name, len(payload),
            )

        if opcode == GS_CRYPT_INIT:
            self._handle_crypt_init(payload)
            return

        # ---- Notify bot engine ----
        if self.on_server_packet:
            asyncio.ensure_future(self.on_server_packet(opcode, payload))

    # L2GameCrypt static suffix (bytes 8-15 of cipher key).
    # Confirmed from L2Net/ServerThread.cs and L2Cipher.cs StaticSuffix.
    _GAME_CRYPT_STATIC = bytes([0xC8, 0x27, 0x93, 0x01, 0xA1, 0x6C, 0x31, 0x97])

    def _handle_blowfish_init(self, payload: bytes) -> None:
        """
        BlowfishInit (opcode 0x00) arrived as plaintext.
        Extract the session XOR key and initialise shadow L2GameCrypt ciphers.

        Packet structure (confirmed from L2Net/ServerThread.cs):
          [1B result/revision][8B dynamic_key][4B enc_flag][4B server_id]
        Cipher key = dynamic_key(8B) + static_suffix(8B: C8 27 93 01 A1 6C 31 97)
        """
        sess = self._session

        # Extract 8-byte dynamic key from payload[1:9] (skip result byte at [0])
        if len(payload) >= 9:
            dynamic_key = bytes(payload[1:9])
        elif len(payload) >= 1:
            dynamic_key = bytes(payload[:min(len(payload), 8)]).ljust(8, b'\x00')
        else:
            dynamic_key = bytes(8)

        real_key = dynamic_key + self._GAME_CRYPT_STATIC

        sess.server_cipher.update_key(real_key)
        sess.client_cipher.update_key(real_key)
        # Initialise shadow XOR ciphers for observation (game server uses L2GameCrypt)
        sess.xor_s2c = L2GameCrypt(real_key)
        # Two separate c2s ciphers: one tracks client state, one tracks server state.
        # This allows packet injection without desyncing the XOR key stream.
        sess.xor_c2s_client = L2GameCrypt(real_key)
        sess.xor_c2s_server = L2GameCrypt(real_key)
        sess.xor_initialized = True
        sess.crypto_initialized = True
        log.info("[GameProxy] BlowfishInit: dynamic=%s  full_key=%s (payload_len=%d)",
                 dynamic_key.hex(), real_key.hex(), len(payload))

    def _handle_crypt_init(self, payload: bytes) -> None:
        """
        CryptInit (opcode 0xAE) — server updates XOR GameCrypt key mid-session.
        Payload: [4-byte XOR seed int]
        Seed XORs into bytes 0-3 of the current DEFAULT_KEY dynamic part.
        Bytes 8-15 always use the static suffix (same as BlowfishInit).
        """
        xor_seed = struct.unpack_from("<I", payload, 0)[0] if len(payload) >= 4 else 0
        # New dynamic bytes 0-3 = DEFAULT_KEY[0:4] XOR seed
        seed_bytes = xor_seed.to_bytes(4, "little")
        new_dynamic = bytearray(DEFAULT_KEY[:8])
        for i in range(4):
            new_dynamic[i] ^= seed_bytes[i]
        xor_key = bytes(new_dynamic) + self._GAME_CRYPT_STATIC
        sess = self._session
        sess.xor_s2c = L2GameCrypt(xor_key)
        sess.xor_c2s_client = L2GameCrypt(xor_key)
        sess.xor_c2s_server = L2GameCrypt(xor_key)
        sess.xor_initialized = True
        log.info("[GameProxy] CryptInit: XOR seed=0x%08X key=%s", xor_seed, xor_key.hex())

    def _handle_client_to_server(self, body: bytes) -> None:
        """Process packet coming from L2 client, forward to real server.

        Re-encrypts every packet using the server-side cipher so that
        injected packets do not desync the XOR key stream.
        """
        sess = self._session

        if sess.crypto_initialized and sess.xor_c2s_client and sess.xor_c2s_server:
            # Decrypt with client-tracking cipher, re-encrypt with server-tracking cipher
            plain = bytes(sess.xor_c2s_client.decrypt(body))
            re_encrypted = bytes(sess.xor_c2s_server.encrypt(plain))
            if self._peer and self._peer._transport:
                self._peer._transport.write(struct.pack("<H", len(re_encrypted) + 2) + re_encrypted)
            opcode = plain[0] if plain else 0xFF
            payload = plain[1:]  # game server C2S has NO checksum
            name = get_client_packet_name(opcode)
            # Default logger level is INFO: DEBUG lines were invisible unless user toggled "Debug C→S".
            if pktlog.isEnabledFor(logging.DEBUG):
                pktlog.debug(
                    "[C→S] 0x%02X %s (%d bytes) plain=%s",
                    opcode, name, len(payload), plain.hex(),
                )
            elif opcode in _C2S_INFO_PLAIN_OPCODES:
                pktlog.info(
                    "[C→S] 0x%02X %s (%d bytes) plain=%s",
                    opcode, name, len(payload), plain.hex(),
                )
        else:
            # Before crypto init — forward transparently
            if self._peer and self._peer._transport:
                self._peer._transport.write(struct.pack("<H", len(body) + 2) + body)

    def send_to_server(self, opcode: int, payload: bytes) -> None:
        """Inject a packet toward the real game server (XOR-encrypted).
        Uses xor_c2s_server so injected packets stay in sync with the server's
        decrypt state.  Client packets are re-encrypted through the same cipher."""
        sess = self._session
        if not sess.crypto_initialized or not sess.xor_c2s_server:
            log.warning("[GameProxy] Cannot inject packet — crypto not initialized yet")
            return
        # Build plaintext body: opcode + payload (NO checksum for game server)
        # Checksums are only used by the login server protocol.
        # Confirmed from l2-unlegits / L2GamePacket — game XOR cipher has no checksum.
        body = bytes([opcode]) + payload
        # XOR-encrypt using the server-tracking cipher
        encrypted = bytes(sess.xor_c2s_server.encrypt(body))
        out = struct.pack("<H", len(encrypted) + 2) + encrypted
        # peer = s2c protocol; s2c._transport = connection to real server
        if self._peer and self._peer._transport and not self._peer._transport.is_closing():
            self._peer._transport.write(out)
            name = get_client_packet_name(opcode)
            log.info("[BOT→S] 0x%02X %s injected (%d bytes) plain=%s", opcode, name, len(body), body.hex())

    def send_to_client(self, opcode: int, payload: bytes) -> None:
        """Inject a fake packet toward the L2 client (XOR-encrypted).
        Called on c2s proto: self._transport is the inbound client connection."""
        sess = self._session
        if not sess.crypto_initialized or not sess.xor_s2c:
            return
        body = bytes([opcode]) + payload
        encrypted = bytes(sess.xor_s2c.encrypt(body))
        out = struct.pack("<H", len(encrypted) + 2) + encrypted
        # self._transport = connection to L2 client
        if self._transport and not self._transport.is_closing():
            self._transport.write(out)

    def connection_lost(self, exc: Exception | None) -> None:
        log.info("[GameProxy %s] Connection lost: %s", self._direction, exc)
        if self._peer and self._peer._transport and not self._peer._transport.is_closing():
            self._peer._transport.close()


class GameProxyServer:
    """
    Listens for L2 client game connections on localhost:7777 and
    proxies them to the real game server.
    """

    def __init__(self, real_host: str, real_port: int = 7777,
                 listen_port: int = 7777, session: GameSession | None = None):
        self.real_host = real_host
        self.real_port = real_port
        self.listen_port = listen_port
        self.session = session or GameSession()
        self._server: asyncio.Server | None = None
        # Bot engine callbacks: set before starting
        self.on_server_packet: Callable[[int, bytes], Awaitable[None]] | None = None
        # Called when a new client connects (new game session started)
        self.on_new_session: Callable[[], None] | None = None
        # Active c2s protocol — used by bot to inject packets
        self._c2s_proto: _GameRelayProtocol | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._server = await loop.create_server(
            self._client_connected,
            host="127.0.0.1",
            port=self.listen_port,
        )
        log.info("[GameProxy] Listening on 127.0.0.1:%d → %s:%d",
                 self.listen_port, self.real_host, self.real_port)

    def _client_connected(self) -> asyncio.Protocol:
        # Create fresh session per client connection
        self.session = GameSession()

        c2s = _GameRelayProtocol(self.session, "c2s")
        s2c = _GameRelayProtocol(self.session, "s2c")
        c2s.set_peer(s2c)

        if self.on_server_packet:
            s2c.on_server_packet = self.on_server_packet

        # Notify BotEngine so it can reset its opcode detector
        if self.on_new_session:
            self.on_new_session()

        self._c2s_proto = c2s

        async def _connect():
            loop = asyncio.get_running_loop()
            try:
                _, _ = await loop.create_connection(
                    lambda: s2c,
                    host=self.real_host,
                    port=self.real_port,
                )
                s2c.set_peer(c2s)
                log.info("[GameProxy] Connected to real game server %s:%d",
                         self.real_host, self.real_port)
            except Exception as exc:
                log.error("[GameProxy] Failed to connect to real game server: %s", exc)
                if c2s._transport:
                    c2s._transport.close()

        asyncio.ensure_future(_connect())
        return c2s

    def inject_to_server(self, opcode: int, payload: bytes) -> None:
        """Bot API: send a packet to the game server."""
        if self._c2s_proto:
            self._c2s_proto.send_to_server(opcode, payload)

    def inject_to_client(self, opcode: int, payload: bytes) -> None:
        """Bot API: send a fake packet to the client."""
        if self._c2s_proto:
            self._c2s_proto.send_to_client(opcode, payload)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
