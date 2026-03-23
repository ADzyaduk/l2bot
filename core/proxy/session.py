"""
Session data shared between LoginProxy and GameProxy for one client connection.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from core.crypto.blowfish_cipher import BlowfishCipher

log = logging.getLogger(__name__)


@dataclass
class LoginSession:
    """State for one Login Server MITM connection."""
    # RSA key received from real server in Init packet
    server_rsa_modulus: bytes = field(default_factory=bytes)
    # Blowfish key received in Login Init packet
    server_blowfish_key: bytes = field(default_factory=bytes)
    # Tokens received after successful auth (forwarded to GameProxy)
    login_ok1: int = 0
    login_ok2: int = 0
    play_ok1: int = 0
    play_ok2: int = 0
    account: str = ""
    # Real game server host/port discovered from ServerList packet
    game_host: str = ""
    game_port: int = 7777
    # Local port our GameProxy listens on (used to patch ServerList)
    listen_game_port: int = 7777
    # Callback: called when real game server is discovered
    on_game_server_discovered: object | None = None  # Callable[[str, int], None]
    # Blowfish cipher for Login Server packets (set after Init packet received)
    login_cipher: BlowfishCipher | None = None


@dataclass
class GameSession:
    """State for one Game Server MITM connection."""
    # Cipher used between our proxy and the real game server
    server_cipher: BlowfishCipher = field(default_factory=BlowfishCipher)
    # Cipher used between the L2 client and our proxy (we generate a fake key)
    client_cipher: BlowfishCipher = field(default_factory=BlowfishCipher)
    # True once BlowfishInit has been processed
    crypto_initialized: bool = False
    # Shadow XOR ciphers — initialised from BlowfishInit / CryptInit
    xor_s2c: object | None = None        # L2GameCrypt for server→client observation
    xor_c2s_client: object | None = None  # L2GameCrypt — tracks CLIENT's encrypt state
    xor_c2s_server: object | None = None  # L2GameCrypt — tracks SERVER's decrypt state
    xor_initialized: bool = False
    # Back-reference to the WorldState (set by bot controller after login)
    world_state: object | None = None
    # Callback for when a parsed packet arrives (set by bot engine)
    on_game_packet: object | None = None  # Callable[[int, bytes], Awaitable[None]]
