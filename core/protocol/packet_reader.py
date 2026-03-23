"""
asyncio Protocol for reading L2 packets from a TCP stream.

L2 packet framing:
  [2 bytes LE: total_length] [body: total_length - 2 bytes]

The body is Blowfish-encrypted. After decryption:
  [1 byte: opcode] [payload...] [4 bytes: checksum]

The reader calls on_packet(opcode, payload_bytes) for each complete packet.
"""
import asyncio
import logging
import struct
from typing import Callable, Awaitable

from core.crypto.blowfish_cipher import BlowfishCipher
from core.crypto.checksum import verify as verify_checksum

log = logging.getLogger(__name__)


class L2PacketReader(asyncio.Protocol):
    """
    asyncio.Protocol that accumulates bytes and emits complete decrypted packets.

    Parameters
    ----------
    cipher : BlowfishCipher
        Active cipher for this connection. Caller updates its key on BlowfishInit.
    on_packet : async callable(opcode: int, data: bytes) -> None
        Called for each decoded packet. Runs in the event loop.
    on_connection_lost : callable() -> None
        Called when the transport is closed.
    decrypt : bool
        Whether to Blowfish-decrypt incoming data. Login server packets
        use a different framing and are NOT Blowfish-encrypted in the same way.
    """

    def __init__(
        self,
        cipher: BlowfishCipher | None,
        on_packet: Callable[[int, bytes], Awaitable[None]],
        on_connection_lost: Callable[[], None] | None = None,
        *,
        decrypt: bool = True,
    ):
        self._cipher = cipher
        self._on_packet = on_packet
        self._on_connection_lost = on_connection_lost
        self._decrypt = decrypt
        self._buf = bytearray()
        self._transport: asyncio.Transport | None = None
        self._loop = asyncio.get_event_loop()

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._transport = transport
        peer = transport.get_extra_info("peername")
        log.debug("Connection made: %s", peer)

    def data_received(self, data: bytes) -> None:
        self._buf += data
        self._process_buffer()

    def _process_buffer(self) -> None:
        while len(self._buf) >= 2:
            total_len = struct.unpack_from("<H", self._buf, 0)[0]
            if total_len < 2:
                log.warning("Malformed packet: total_len=%d, discarding byte", total_len)
                self._buf = self._buf[1:]
                continue
            body_len = total_len - 2
            if len(self._buf) < total_len:
                break  # wait for more data

            raw_body = bytes(self._buf[2:total_len])
            self._buf = self._buf[total_len:]

            if self._decrypt and self._cipher:
                try:
                    raw_body = self._cipher.decrypt(raw_body)
                except Exception as exc:
                    log.error("Blowfish decrypt failed: %s", exc)
                    continue

                # Verify checksum (last 4 bytes)
                if not verify_checksum(raw_body):
                    log.warning("Checksum mismatch on packet (len=%d)", len(raw_body))
                    # don't drop — some servers don't use checksums correctly
                    # continue  # uncomment to enforce strict checksum

            if len(raw_body) < 1:
                continue

            opcode = raw_body[0]
            # payload excludes opcode and the trailing 4-byte checksum
            payload = raw_body[1:-4] if self._decrypt and len(raw_body) > 5 else raw_body[1:]

            asyncio.ensure_future(self._on_packet(opcode, payload))

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            log.info("Connection lost: %s", exc)
        else:
            log.info("Connection closed cleanly")
        if self._on_connection_lost:
            self._on_connection_lost()

    def send_raw(self, data: bytes) -> None:
        """Send raw bytes (already framed) on this transport."""
        if self._transport and not self._transport.is_closing():
            self._transport.write(data)

    def close(self) -> None:
        if self._transport:
            self._transport.close()
