"""
Dynamic opcode detector for Teon (Elmorelab Interlude).

The Teon server applies a per-session XOR key byte to all game server opcodes.
The key is consistent within a session but changes every connection.

Detection method:
  1. Watch for a burst of packets with exactly 187-byte payload → NpcInfo
  2. xor_key = observed_npcinfo_opcode XOR NPCINFO_BASE (0x16)
  3. All other session opcodes = base_opcode XOR xor_key

Base opcodes derived from session-2 logs (known key = 0x7A):
  teon_s2_opcode XOR 0x7A = base_opcode
"""
import logging
from typing import Callable

log = logging.getLogger(__name__)

# Base opcodes for Teon server (session-2 observed XOR'd with 0x7A)
# NpcInfo=0x16 and MoveToPoint=0x01 confirmed via standard L2J match.
# Others derived from session-2 observations.
TEON_BASE_OPCODES: dict[str, int] = {
    "CharList":         0x13,   # 0x69 ^ 0x7A
    "CharSelected":     0x15,   # 0x6F ^ 0x7A
    # UserInfo = 0x04 (standard L2J CT2 anchor). Session-2 observed as 0x7E ^ 0x7A = 0x04.
    # (Was wrongly set to 0x1B before; 0x1B = ItemList on Teon, not UserInfo.)
    "UserInfo":         0x04,   # 0x7E ^ 0x7A  (= standard L2J CT2)
    "NpcInfo":          0x16,   # 0x6C ^ 0x7A  (= standard L2J anchor)
    "MoveToPoint":      0x01,   # 0x7B ^ 0x7A  (= standard L2J)
    "StatusUpdate":     0x6D,   # 0x17 ^ 0x7A
    # SkillList = 0x58 (standard L2J CT2). Session-2 observed as 0x22 ^ 0x7A = 0x58.
    "SkillList":        0x58,   # 0x22 ^ 0x7A  (= standard L2J CT2)
    # Full inventory list (L2J Interlude 0x1B); Teon XOR applies like other S2C opcodes.
    "ItemList":         0x1B,
    # Partial inventory (L2J Interlude 0x21); stack changes / removals after use, etc.
    "InventoryUpdate":  0x21,
    "SystemMessage":    0x62,   # estimated
    "LogoutOk":         0x7F,   # 0x05 ^ 0x7A
    "LeaveWorld":       0x6E,   # 0x14 ^ 0x7A
    "Say2":             0x54,   # 0x2E ^ 0x7A
    # "ValidatePosition": 0x0E — WRONG on Teon, 0x0E packets contain non-position data
    "StopMove":         0x2D,   # 0x57 ^ 0x7A
    "ChangeWaitType":   0x25,   # 0x5F ^ 0x7A
    # L2J Interlude: 0x06 Die carries objectId + flags (>>4B). Teon observed SC_Die is 4B → Die2 ^ xor_key.
    "Die":              0x06,
    "Die2":             0x12,   # 4B objectId — primary death notify on Teon (see registry SC_Die)
    "DeleteObject":     0x72,   # estimated from std L2J 0x08 ^ 0x7A
    "TargetSelected":   0x47,   # 0x3D ^ 0x7A
    "SpawnItem":        0x0C,   # 32-byte packets after mob death (session-2: 0x76)
    "Attack":           0x60,   # 20-byte damage packets during combat (session-2: 0x1A)
    "SkillCoolTime":    0x6A,   # 0x10 ^ 0x7A  (estimated)
    # MagicSkillLaunched (L2J Interlude S2C 0x48) — not C2S RequestGetItem
    "MagicSkillLaunched": 0x48,
    # Active effect icons / buff list (L2J-style AbnormalStatusUpdate 0x7F)
    "AbnormalStatusUpdate": 0x7F,
    # Party small window — HP/MP (L2J Interlude 0x4E–0x50)
    "PartySmallWindowAll": 0x4E,
    "PartySmallWindowAdd": 0x4F,
    "PartySmallWindowDelete": 0x50,
    # Party member buff list (L2J Interlude 0xEE)
    "PartySpelled": 0xEE,
    # Short buff icon strip (common L2J-style base 0x91; verify on capture if missing)
    "ShortBuffStatusUpdate": 0x91,
    # Teon sends a SECOND StatusUpdate on base 0x0E (standard L2J StatusUpdate opcode).
    # Contains mob HP data (ATTR_MAX_HP, ATTR_CUR_HP). Same format as StatusUpdate.
    "StatusUpdate2":    0x0E,   # standard L2J StatusUpdate opcode — Teon uses it alongside 0x6D
}

# NpcInfo payload size is fixed at 187 bytes on Teon (detector anchor).
NPCINFO_PAYLOAD_SIZE = 187
# Before XOR key is known, BotEngine buffers S2C payloads in this length range as *candidate*
# NpcInfo (replayed only for opcode matching NpcInfo after detection). Wider than 187 so
# minor chronicle / padding differences still replay; see logs if false positives appear.
NPCINFO_PREBUF_LEN_MIN = 180
NPCINFO_PREBUF_LEN_MAX = 210

# Minimum NpcInfo packets needed before declaring detection complete
MIN_NPCINFO_COUNT = 5


class OpcodeDetector:
    """
    Observes packets after game entry to detect the per-session XOR key.

    Usage:
        detector = OpcodeDetector()
        detector.on_ready = lambda opcodes: bot.update_opcodes(opcodes)

        # In packet dispatch loop:
        detector.feed(opcode, len(payload))
    """

    def __init__(self) -> None:
        # opcode → list of payload sizes seen
        self._size_counts: dict[int, list[int]] = {}
        self.xor_key: int | None = None
        self.opcodes: dict[str, int] = {}   # name → session opcode
        self.ready = False
        # Called once when detection is complete: callback(opcodes_dict)
        self.on_ready: Callable[[dict[str, int]], None] | None = None

    def reset(self) -> None:
        """Reset detection state (keep on_ready callback intact)."""
        self._size_counts.clear()
        self.xor_key = None
        self.opcodes.clear()
        self.ready = False

    def feed(self, opcode: int, payload_len: int) -> None:
        """Feed a single observed (opcode, payload_length) pair."""
        if self.ready:
            return
        bucket = self._size_counts.setdefault(opcode, [])
        bucket.append(payload_len)
        self._try_detect()

    def _try_detect(self) -> None:
        """Check if we can identify the NpcInfo opcode."""
        for op, sizes in self._size_counts.items():
            count_187 = sum(1 for s in sizes if s == NPCINFO_PAYLOAD_SIZE)
            if count_187 >= MIN_NPCINFO_COUNT:
                self._finalize(op)
                return

    def _finalize(self, npcinfo_opcode: int) -> None:
        key = npcinfo_opcode ^ TEON_BASE_OPCODES["NpcInfo"]
        self.xor_key = key
        self.opcodes = {name: base ^ key for name, base in TEON_BASE_OPCODES.items()}

        # Verify with MoveToPoint if we have data
        expected_move = TEON_BASE_OPCODES["MoveToPoint"] ^ key
        move_counts = self._size_counts.get(expected_move, [])
        count_24 = sum(1 for s in move_counts if s == 24)

        log.info(
            "[OpcodeDetector] XOR key=0x%02X  NpcInfo=0x%02X  MoveToPoint=0x%02X"
            "  UserInfo=0x%02X  StatusUpdate=0x%02X  StatusUpdate2=0x%02X"
            "  (MoveToPoint 24B seen: %d)",
            key,
            self.opcodes["NpcInfo"],
            self.opcodes["MoveToPoint"],
            self.opcodes["UserInfo"],
            self.opcodes["StatusUpdate"],
            self.opcodes["StatusUpdate2"],
            count_24,
        )

        self.ready = True
        if self.on_ready:
            self.on_ready(dict(self.opcodes))
