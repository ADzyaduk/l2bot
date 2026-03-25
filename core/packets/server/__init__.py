"""
Server → Client packet parsers for Lineage 2 Interlude.

Each class parses a raw payload (bytes after opcode, before checksum)
using BasePacket cursor helpers.
"""
import struct
from dataclasses import dataclass, field
from typing import Optional

from core.protocol.base_packet import BasePacket


# ------------------------------------------------------------------ #
# SC_UserInfo  0x04  —  my character full info
# ------------------------------------------------------------------ #
@dataclass
class UserInfo:
    opcode = 0x04   # standard L2J CT2 Interlude base opcode

    object_id: int = 0
    x: int = 0
    y: int = 0
    z: int = 0
    heading: int = 0
    race: int = 0
    sex: int = 0
    class_id: int = 0
    level: int = 0
    exp: int = 0
    str_: int = 0
    dex: int = 0
    con: int = 0
    int_: int = 0
    wit: int = 0
    men: int = 0
    max_hp: int = 1
    cur_hp: int = 0
    max_mp: int = 1
    cur_mp: int = 0
    sp: int = 0
    name: str = ""
    title: str = ""

    @classmethod
    def parse(cls, payload: bytes) -> "UserInfo":
        """Parse UserInfo. Teon field order: x, y, z, heading, objectId, name, ..."""
        p = BasePacket(payload)
        self = cls()
        try:
            self.x = p.read_int()             # 0: x coordinate
            self.y = p.read_int()             # 4: y coordinate
            self.z = p.read_int()             # 8: z coordinate
            self.heading = p.read_int()       # 12: heading
            self.object_id = p.read_int()     # 16: objectId
            self.name = p.read_string()       # 20: name (UTF-16LE)
            # After name: race, sex, classId, level, exp(8B), stats, HP/MP
            self.race = p.read_int()
            self.sex = p.read_int()
            self.class_id = p.read_int()
            self.level = p.read_int()
            self.exp = p.read_long()          # exp: 8 bytes
            self.str_ = p.read_int()
            self.dex = p.read_int()
            self.con = p.read_int()
            self.int_ = p.read_int()
            self.wit = p.read_int()
            self.men = p.read_int()
            self.max_hp = p.read_int()
            self.cur_hp = p.read_int()
            self.max_mp = p.read_int()
            self.cur_mp = p.read_int()
            self.sp = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_NpcInfo  0x16  —  NPC / monster appeared in range
# ------------------------------------------------------------------ #
@dataclass
class NpcInfo:
    opcode = 0x6C   # Teon (Elmorelab Interlude) — standard L2J uses 0x16

    object_id: int = 0
    npc_type_id: int = 0      # npcId + 1_000_000
    is_attackable: bool = False
    x: int = 0
    y: int = 0
    z: int = 0
    heading: int = 0
    name: str = ""
    title: str = ""
    is_dead: bool = False     # isDead byte from packet
    is_summoned: bool = False  # isSummoned byte (pets / summons — skip as combat targets when configured)
    hp_pct: float = 100.0     # 0-100, only for aggro monsters (unreliable on Teon)

    @property
    def npc_id(self) -> int:
        return self.npc_type_id - 1_000_000

    @classmethod
    def parse(cls, payload: bytes) -> "NpcInfo":
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
            self.npc_type_id = p.read_int()
            self.is_attackable = bool(p.read_int())
            self.x = p.read_int()
            self.y = p.read_int()
            self.z = p.read_int()
            self.heading = p.read_int()
            p.read_int()        # unknown
            p.read_int()        # mAtk
            p.read_int()        # pAtk
            p.read_int()        # runSpeed
            p.read_int()        # walkSpeed
            p.read_int()        # swimRunSpeed
            p.read_int()        # swimWalkSpeed
            p.read_int()        # flRunSpeed
            p.read_int()        # flWalkSpeed
            p.read_int()        # flyRunSpeed
            p.read_int()        # flyWalkSpeed
            p.read_double()     # movMult (writeF = 8 bytes)
            p.read_double()     # atkSpeedMult
            p.read_double()     # colRadius
            p.read_double()     # colHeight
            p.read_int()        # rHandId
            p.read_int()        # unknown
            p.read_int()        # lHandId
            p.read_byte()       # nameAboveChar
            p.read_byte()       # isRunning
            p.read_byte()       # inCombat
            self.is_dead = bool(p.read_byte())   # isDead
            self.is_summoned = bool(p.read_byte())  # isSummoned
            self.name = p.read_string()
            self.title = p.read_string()
            # After title: standard L2J Interlude NpcInfo remaining fields
            if p.remaining() >= 28:
                p.read_int()    # pvpFlag
                p.read_int()    # karma
                p.read_int()    # abnormalEffect
                p.read_int()    # clanId
                p.read_int()    # clanCrest
                p.read_int()    # allyId
                p.read_int()    # allyCrest
            if p.remaining() >= 18:
                p.read_byte()   # isFlying
                p.read_byte()   # team
                p.read_double() # collisionRadius (repeat)
                p.read_double() # collisionHeight (repeat)
            if p.remaining() >= 4:
                p.read_int()    # enchant or unknown
            if p.remaining() >= 4:
                self.hp_pct = float(p.read_int())   # curHpPercent (0-100)
            if p.remaining() >= 4:
                p.read_int()    # curMpPercent
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_DeleteObject  0x08  —  object removed from sight
# ------------------------------------------------------------------ #
@dataclass
class DeleteObject:
    opcode = 0x08

    object_id: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "DeleteObject":
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_StatusUpdate  0x0E  —  HP/MP/exp attribute update for any object
# ------------------------------------------------------------------ #

# Known attribute IDs
ATTR_LEVEL    = 0x01
ATTR_CUR_HP   = 0x09
ATTR_MAX_HP   = 0x0A
ATTR_CUR_MP   = 0x0B
ATTR_MAX_MP   = 0x0C
ATTR_CUR_EXP  = 0x0D
ATTR_SP       = 0x0F
ATTR_CUR_CP   = 0x21
ATTR_MAX_CP   = 0x22

@dataclass
class StatusUpdate:
    opcode = 0x17   # Teon (Elmorelab Interlude) — standard L2J uses 0x0E

    object_id: int = 0
    attrs: dict = field(default_factory=dict)   # attrId → value

    @classmethod
    def parse(cls, payload: bytes) -> "StatusUpdate":
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
            count = p.read_int()
            # Sanity check: count must be reasonable (≤10) and enough bytes remaining
            if count < 0 or count > 10 or p.remaining() < count * 8:
                # Teon 0x0E variant: no count field, try reading attrs directly
                # Rewind by treating "count" as first attr_id
                attr_id = count
                if p.remaining() >= 4:
                    value = p.read_int()
                    self.attrs[attr_id] = value
                while p.remaining() >= 8:
                    attr_id = p.read_int()
                    value = p.read_int()
                    self.attrs[attr_id] = value
            else:
                for _ in range(count):
                    attr_id = p.read_int()
                    value = p.read_int()
                    self.attrs[attr_id] = value
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_MoveToPoint  0x01  —  unit started moving
# ------------------------------------------------------------------ #
@dataclass
class MoveToPoint:
    opcode = 0x7B   # Teon (Elmorelab Interlude) — standard L2J uses 0x01

    object_id: int = 0
    dest_x: int = 0
    dest_y: int = 0
    dest_z: int = 0
    orig_x: int = 0
    orig_y: int = 0
    orig_z: int = 0

    has_orig_z: bool = False

    @classmethod
    def parse(cls, payload: bytes) -> "MoveToPoint":
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
            self.dest_x = p.read_int()
            self.dest_y = p.read_int()
            self.dest_z = p.read_int()
            self.orig_x = p.read_int()
            self.orig_y = p.read_int()
            if p.remaining() >= 4:
                self.orig_z = p.read_int()
                self.has_orig_z = True
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_ChangeWaitType  (base 0x25 Teon) —  sit / stand / movement mode
# L2J: writeD(objectId); writeD(type). Binary forks: 0=sit 1=stand (Acis) or inverted.
# ------------------------------------------------------------------ #
@dataclass
class ChangeWaitType:
    opcode = 0x25

    object_id: int = 0
    wait_type: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "ChangeWaitType":
        self = cls()
        if len(payload) < 8:
            return self
        try:
            self.object_id, self.wait_type = struct.unpack_from("<ii", payload, 0)
        except struct.error:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_Die  0x06  —  unit died
# ------------------------------------------------------------------ #
@dataclass
class Die:
    opcode = 0x68   # Teon: 4-byte payload = objectId. Standard L2J uses 0x06

    object_id: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "Die":
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_ValidatePosition  —  server corrects/confirms character position
# ------------------------------------------------------------------ #
@dataclass
class ValidatePosition:
    opcode = 0x0E   # Teon: 0x0E (base 0x0E ^ xor_key 0x00)

    object_id: int = 0
    x: int = 0
    y: int = 0
    z: int = 0
    heading: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "ValidatePosition":
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
            self.x = p.read_int()
            self.y = p.read_int()
            self.z = p.read_int()
            self.heading = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_TargetSelected  0x24  —  server confirms our target
# ------------------------------------------------------------------ #
@dataclass
class TargetSelected:
    opcode = 0x24

    object_id: int = 0    # who selected a target (their objectId)
    x: int = 0            # selector's x position
    y: int = 0            # selector's y position
    z: int = 0            # selector's z position

    @classmethod
    def parse(cls, payload: bytes) -> "TargetSelected":
        """Parse TargetSelected. Teon sends 16 bytes: objectId + x + y + z."""
        p = BasePacket(payload)
        self = cls()
        try:
            self.object_id = p.read_int()
            self.x = p.read_int()
            self.y = p.read_int()
            self.z = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_DropItem (0x0C)  —  item dropped on ground (from mob/player)
# Standard L2J DropItem format: dropper + itemObjId + itemId + count + x/y/z + stackable
# ------------------------------------------------------------------ #
@dataclass
class SpawnItem:
    opcode = 0x0C   # Teon base opcode — actually DropItem format

    dropper_id: int = 0   # objectId of mob/player who dropped it
    object_id: int = 0    # item's unique objectId (used for pickup)
    item_id: int = 0      # item template ID
    x: int = 0
    y: int = 0
    z: int = 0
    stackable: int = 0
    count: int = 1

    @classmethod
    def parse(cls, payload: bytes) -> "SpawnItem":
        p = BasePacket(payload)
        self = cls()
        try:
            self.dropper_id = p.read_int()
            self.object_id = p.read_int()
            self.item_id = p.read_int()
            self.x = p.read_int()
            self.y = p.read_int()
            self.z = p.read_int()
            if p.remaining() >= 4:
                self.stackable = p.read_int()
            if p.remaining() >= 4:
                self.count = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_SkillList 0x58 — known skills (id, level, passive); no names in Interlude
# ------------------------------------------------------------------ #
@dataclass
class SkillList:
    """L2J Interlude format: count, then per skill: passive(D), level(D), id(D), unk(C)."""

    skills: list[tuple[int, int, bool]] = field(default_factory=list)

    @classmethod
    def parse(cls, payload: bytes) -> "SkillList":
        p = BasePacket(payload)
        self = cls()
        try:
            n = p.read_int()
            for _ in range(max(0, min(n, 5000))):
                passive_flag = p.read_int()
                level = p.read_int()
                sid = p.read_int()
                if p.remaining() >= 1:
                    p.read_byte()
                self.skills.append((sid, level, passive_flag != 0))
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_MagicSkillLaunched 0x48 (L2J Interlude) — caster, target, skill, level, hit/reuse, x,y,z
# Same opcode as C2S RequestGetItem; direction distinguishes. Payload is 32 or 36 bytes (9× int32).
# ------------------------------------------------------------------ #
@dataclass
class MagicSkillLaunched:
    caster_id: int = 0
    target_id: int = 0
    skill_id: int = 0
    skill_level: int = 0
    hit_time: int = 0
    reuse_delay: int = 0
    x: int = 0
    y: int = 0
    z: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "MagicSkillLaunched":
        self = cls()
        n = len(payload)
        if n < 32:
            return self
        try:
            if n >= 36:
                (
                    self.caster_id,
                    self.target_id,
                    self.skill_id,
                    self.skill_level,
                    self.hit_time,
                    self.reuse_delay,
                    self.x,
                    self.y,
                    self.z,
                ) = struct.unpack_from("<9i", payload, 0)
            else:
                (
                    self.caster_id,
                    self.target_id,
                    self.skill_id,
                    self.skill_level,
                    self.hit_time,
                    self.reuse_delay,
                    self.x,
                    self.y,
                ) = struct.unpack_from("<8i", payload, 0)
        except struct.error:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_Attack  —  damage / hit notification
# ------------------------------------------------------------------ #
@dataclass
class Attack:
    opcode = 0x60   # Teon base opcode

    attacker_id: int = 0
    target_id: int = 0
    damage: int = 0
    flags: int = 0
    x: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "Attack":
        p = BasePacket(payload)
        self = cls()
        try:
            self.attacker_id = p.read_int()
            self.target_id = p.read_int()
            self.damage = p.read_int()
            self.flags = p.read_int()
            self.x = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_ItemList 0x1B — full inventory (L2J Interlude layout)
# H showWindow, H count, then per item fixed block (type1, objectId, itemId, count, ...).
# ------------------------------------------------------------------ #
@dataclass
class ItemList:
    """Inventory snapshot from server. item_id = template id (datapack)."""

    show_window: bool = False
    items: list[tuple[int, int, int]] = field(default_factory=list)
    # (object_id, item_id template, stack count)

    # Bytes per item after L2J Interlude ItemList loop body (incl. 8-byte aug slot).
    _ENTRY_STRIDE = 36

    @classmethod
    def parse(cls, payload: bytes) -> "ItemList":
        p = BasePacket(payload)
        self = cls()
        try:
            show = p.read_ushort()
            self.show_window = show != 0
            count = p.read_ushort()
            if count < 0 or count > 5000:
                return self
            for _ in range(count):
                if p.remaining() < cls._ENTRY_STRIDE:
                    break
                p.read_ushort()  # type1
                oid = p.read_int()
                iid = p.read_int()
                cnt = p.read_int()
                self.items.append((oid, iid, cnt))
                p.read_bytes(cls._ENTRY_STRIDE - 14)  # rest of entry
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_SkillCoolTime — reuse delays (L2J: count D then per row D skillId, D remain, D total)
# ------------------------------------------------------------------ #
@dataclass
class SkillCoolTime:
    rows: list[tuple[int, int, int]] = field(default_factory=list)
    # skill_id, remaining_ms (or server units), total_ms

    @classmethod
    def parse(cls, payload: bytes) -> "SkillCoolTime":
        p = BasePacket(payload)
        self = cls()
        try:
            if p.remaining() >= 4:
                n = p.read_int()
                if 0 < n <= 500 and p.remaining() >= n * 12:
                    for _ in range(n):
                        sid = p.read_int()
                        rem = p.read_int()
                        tot = p.read_int()
                        self.rows.append((sid, rem, tot))
                    return self
            p = BasePacket(payload)
            while p.remaining() >= 12:
                self.rows.append((p.read_int(), p.read_int(), p.read_int()))
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_AbnormalStatusUpdate 0x7F — buffs / abnormal effects (skill ids + duration)
# ------------------------------------------------------------------ #
def _abnormal_skill_id_sane(sid: int) -> bool:
    """Reject obvious garbage from wrong layout (oid fragments as skill id)."""
    return 1 <= sid <= 200_000


@dataclass
class AbnormalStatusUpdate:
    object_id: int = 0
    effects: list[tuple[int, int, int]] = field(default_factory=list)
    # skill_id, skill_level, duration
    # True when payload is a strict «oid + count 0» (or ii layout) empty list — not a parse fallback.
    explicit_empty: bool = False

    _EFFECT_STRIDE = 10  # int32 + int16 + int32

    @classmethod
    def _read_effects(
        cls, payload: bytes, offset: int, count: int
    ) -> tuple[list[tuple[int, int, int]], int] | None:
        end = offset + count * cls._EFFECT_STRIDE
        if count <= 0 or count > 64 or end > len(payload):
            return None
        effects: list[tuple[int, int, int]] = []
        off = offset
        for _ in range(count):
            sid, lvl, dur = struct.unpack_from("<ihI", payload, off)
            if not _abnormal_skill_id_sane(sid):
                return None
            effects.append((sid, lvl, dur))
            off += cls._EFFECT_STRIDE
        return effects, end

    @classmethod
    def _try_legacy_abnormal(cls, payload: bytes) -> "AbnormalStatusUpdate | None":
        """L2J Interlude: H count or D oid + H count + effects."""
        p = BasePacket(payload)
        need_per = cls._EFFECT_STRIDE
        n = len(payload)
        try:
            p._pos = 0
            count_a = p.read_ushort()
            need_a = 2 + count_a * need_per
            count_b = 0
            oid_b = 0
            if n >= 6:
                p._pos = 0
                oid_b = p.read_int()
                count_b = p.read_ushort()
            need_b = 6 + count_b * need_per if count_b > 0 else 0

            use_b = (
                0 < count_b <= 64
                and n >= need_b
                and (count_a > 64 or n < need_a or abs(n - need_b) < abs(n - need_a))
            )
            if use_b and need_b > 0:
                p._pos = 6
                oid = oid_b
                count = count_b
            elif 0 < count_a <= 64 and n >= need_a:
                p._pos = 2
                oid = 0
                count = count_a
            else:
                return None

            if p.remaining() < count * need_per:
                return None
            effects: list[tuple[int, int, int]] = []
            for _ in range(count):
                sid = p.read_int()
                lvl = p.read_short()
                dur = p.read_int()
                if not _abnormal_skill_id_sane(sid):
                    return None
                effects.append((sid, lvl, dur))
            return AbnormalStatusUpdate(oid, effects)
        except Exception:
            return None

    @classmethod
    def _try_empty_abnormal(cls, payload: bytes) -> "AbnormalStatusUpdate | None":
        """Full snapshot with zero effects: int32 oid + uint16 count 0 (+ optional 2-byte pad), or ii with count 0.

        We require oid != 0 so all-zero / oid-0 stubs are not treated as authoritative (avoids rebuff spam).
        """
        n = len(payload)
        if n == 6:
            oid, cnt = struct.unpack_from("<iH", payload, 0)
            if cnt == 0 and oid != 0:
                return AbnormalStatusUpdate(oid, [], explicit_empty=True)
            return None
        if n == 8:
            oid, cnt = struct.unpack_from("<iH", payload, 0)
            if cnt == 0 and oid != 0:
                return AbnormalStatusUpdate(oid, [], explicit_empty=True)
            oid2, cnt2 = struct.unpack_from("<ii", payload, 0)
            if cnt2 == 0 and oid2 != 0:
                return AbnormalStatusUpdate(oid2, [], explicit_empty=True)
            return None
        return None

    @classmethod
    def _try_dword_count(cls, payload: bytes) -> "AbnormalStatusUpdate | None":
        """Some forks: int32 count @0, then effects (no object id)."""
        n = len(payload)
        if n < 4:
            return None
        count = struct.unpack_from("<i", payload, 0)[0]
        got = cls._read_effects(payload, 4, count)
        if got is None:
            return None
        effects, end = got
        if end > n or n - end > 2:
            return None
        return AbnormalStatusUpdate(0, effects)

    @classmethod
    def _try_oid_dword_count(cls, payload: bytes) -> "AbnormalStatusUpdate | None":
        """Some Teon / private: int32 objectId, int32 count, then effects."""
        n = len(payload)
        if n < 8:
            return None
        oid, count = struct.unpack_from("<ii", payload, 0)
        if oid == 0 or count <= 0 or count > 64:
            return None
        got = cls._read_effects(payload, 8, count)
        if got is None:
            return None
        effects, end = got
        if end > n or n - end > 2:
            return None
        return AbnormalStatusUpdate(oid, effects)

    @classmethod
    def _try_byte_count(cls, payload: bytes) -> "AbnormalStatusUpdate | None":
        """Rare: uint8 count @0, then effects."""
        n = len(payload)
        if n < 1:
            return None
        count = payload[0]
        if count == 0 or count > 64:
            return None
        got = cls._read_effects(payload, 1, count)
        if got is None:
            return None
        effects, end = got
        if end > n or n - end > 2:
            return None
        return AbnormalStatusUpdate(0, effects)

    @classmethod
    def parse(cls, payload: bytes) -> "AbnormalStatusUpdate":
        if not payload:
            return AbnormalStatusUpdate()
        empty = cls._try_empty_abnormal(payload)
        if empty is not None:
            return empty
        opts: list[tuple[int, AbnormalStatusUpdate]] = []

        def push(consumed: int, pkt: AbnormalStatusUpdate) -> None:
            if not pkt.effects:
                return
            pad = len(payload) - consumed
            exact = 10_000 if 0 <= pad <= 2 else 0
            opts.append((exact + 100 * len(pkt.effects) + consumed, pkt))

        leg = cls._try_legacy_abnormal(payload)
        if leg is not None and leg.effects:
            c = 6 + len(leg.effects) * cls._EFFECT_STRIDE if leg.object_id else 2 + len(leg.effects) * cls._EFFECT_STRIDE
            push(c, leg)

        for try_fn in (
            cls._try_oid_dword_count,
            cls._try_dword_count,
            cls._try_byte_count,
        ):
            alt = try_fn(payload)
            if alt is None or not alt.effects:
                continue
            if try_fn is cls._try_oid_dword_count:
                cons = 8 + len(alt.effects) * cls._EFFECT_STRIDE
            elif try_fn is cls._try_dword_count:
                cons = 4 + len(alt.effects) * cls._EFFECT_STRIDE
            else:
                cons = 1 + len(alt.effects) * cls._EFFECT_STRIDE
            push(cons, alt)

        if not opts:
            return AbnormalStatusUpdate()
        return max(opts, key=lambda x: x[0])[1]


# ------------------------------------------------------------------ #
# Party small window — HP/MP/CP bars (L2J Interlude base ~0x4E / 0x4F / 0x50)
# ------------------------------------------------------------------ #
@dataclass
class PartyMemberInfo:
    """One row from PartySmallWindowAll / PartySmallWindowAdd."""

    object_id: int = 0
    name: str = ""
    class_id: int = 0
    level: int = 0
    cur_hp: int = 0
    max_hp: int = 0
    cur_mp: int = 0
    max_mp: int = 0
    cur_cp: int = 0
    max_cp: int = 0


def _parse_party_member_row(p: BasePacket) -> Optional[PartyMemberInfo]:
    """L2J: S, objectId, classId, curHp, maxHp, curMp, maxMp, curCp, [maxCp,] level."""
    try:
        if p.remaining() < 4:
            return None
        name = p.read_string()
        need = 6 * 4  # oid, class, hp×2, mp×2, curCp
        if p.remaining() < need:
            return None
        oid = p.read_int()
        class_id = p.read_int()
        cur_hp = p.read_int()
        max_hp = p.read_int()
        cur_mp = p.read_int()
        max_mp = p.read_int()
        cur_cp = p.read_int()
        max_cp = 0
        level = 0
        if p.remaining() >= 8:
            max_cp = p.read_int()
            level = p.read_int()
        elif p.remaining() >= 4:
            level = p.read_int()
        else:
            return None
        return PartyMemberInfo(
            object_id=oid,
            name=name,
            class_id=class_id,
            level=level,
            cur_hp=cur_hp,
            max_hp=max_hp,
            cur_mp=cur_mp,
            max_mp=max_mp,
            cur_cp=cur_cp,
            max_cp=max_cp,
        )
    except Exception:
        return None


@dataclass
class PartySmallWindowAll:
    """Full party list (replaces local party state)."""

    opcode = 0x4E
    declared_count: int = -1
    members: list[PartyMemberInfo] = field(default_factory=list)

    @classmethod
    def parse(cls, payload: bytes) -> "PartySmallWindowAll":
        self = cls()
        if len(payload) < 4:
            return self
        p = BasePacket(payload)
        try:
            count = p.read_int()
            self.declared_count = count
            if count < 0 or count > 9:
                return self
            if count == 0:
                return self
            for _ in range(count):
                m = _parse_party_member_row(p)
                if m is None or m.object_id == 0:
                    break
                self.members.append(m)
        except Exception:
            pass
        return self


@dataclass
class PartySmallWindowAdd:
    opcode = 0x4F

    member: Optional[PartyMemberInfo] = None

    @classmethod
    def parse(cls, payload: bytes) -> "PartySmallWindowAdd":
        self = cls()
        p = BasePacket(payload)
        self.member = _parse_party_member_row(p)
        return self


@dataclass
class PartySmallWindowDelete:
    opcode = 0x50

    object_id: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "PartySmallWindowDelete":
        self = cls()
        if len(payload) >= 4:
            try:
                self.object_id = struct.unpack_from("<i", payload, 0)[0]
            except struct.error:
                pass
        return self


@dataclass
class PartySmallWindowUpdate:
    """Real-time HP/MP/CP update for one party member."""

    opcode = 0x52
    object_id: int = 0
    cur_hp: int = 0
    max_hp: int = 0
    cur_mp: int = 0
    max_mp: int = 0
    cur_cp: int = 0
    max_cp: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "PartySmallWindowUpdate":
        self = cls()
        if len(payload) < 28:
            return self
        try:
            p = BasePacket(payload)
            self.object_id = p.read_int()
            self.cur_hp = p.read_int()
            self.max_hp = p.read_int()
            self.cur_mp = p.read_int()
            self.max_mp = p.read_int()
            self.cur_cp = p.read_int()
            self.max_cp = p.read_int()
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_PartySpelled (L2J Interlude base ~0xEE) — buff list for one party member
# ------------------------------------------------------------------ #
@dataclass
class PartySpelled:
    object_id: int = 0
    effects: list[tuple[int, int, int]] = field(default_factory=list)  # skill_id, level, duration

    _EFFECT_STRIDE = 10

    @classmethod
    def parse(cls, payload: bytes) -> "PartySpelled":
        self = cls()
        if len(payload) < 6:
            return self
        try:
            oid = struct.unpack_from("<i", payload, 0)[0]
            cnt = struct.unpack_from("<H", payload, 4)[0]
            if oid == 0 or cnt <= 0 or cnt > 64:
                return self
            off = 6
            effects: list[tuple[int, int, int]] = []
            for _ in range(cnt):
                if off + cls._EFFECT_STRIDE > len(payload):
                    return self
                sid, lvl, dur = struct.unpack_from("<ihI", payload, off)
                if not _abnormal_skill_id_sane(sid):
                    return cls()
                effects.append((sid, lvl, dur))
                off += cls._EFFECT_STRIDE
            self.object_id = oid
            self.effects = effects
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_ShortBuffStatusUpdate (L2J-style base ~0x91) — compact buff row(s)
# ------------------------------------------------------------------ #
@dataclass
class ShortBuffStatusUpdate:
    """Either 12B (skillId, skillLvl, duration as 3×DWORD) or 16B (+ leading objectId)."""

    object_id: int = 0
    skill_id: int = 0
    skill_level: int = 0
    duration: int = 0

    @classmethod
    def parse(cls, payload: bytes) -> "ShortBuffStatusUpdate":
        self = cls()
        n = len(payload)
        try:
            if n >= 16:
                self.object_id = struct.unpack_from("<i", payload, 0)[0]
                self.skill_id = struct.unpack_from("<i", payload, 4)[0]
                self.skill_level = struct.unpack_from("<i", payload, 8)[0]
                self.duration = struct.unpack_from("<i", payload, 12)[0]
            elif n >= 12:
                self.skill_id = struct.unpack_from("<i", payload, 0)[0]
                self.skill_level = struct.unpack_from("<i", payload, 4)[0]
                self.duration = struct.unpack_from("<i", payload, 8)[0]
        except Exception:
            pass
        return self


# ------------------------------------------------------------------ #
# SC_InventoryUpdate (L2J Interlude base ~0x21) — partial inventory sync
# ------------------------------------------------------------------ #
@dataclass
class InventoryUpdate:
    """Rows (object_id, template_id, count). template_id==0 and count==0 → remove object_id."""

    items: list[tuple[int, int, int]] = field(default_factory=list)

    _ROW_TAIL = 22  # after type1+oid+iid+cnt inside 36-byte ItemList row

    @classmethod
    def parse(cls, payload: bytes) -> "InventoryUpdate":
        self = cls()
        if not payload:
            return self
        # ItemList is H show, H count, count × 36-byte rows. InventoryUpdate delta is
        # H count, then per-row H(mod) … — do not parse as ItemList unless length fits.
        if len(payload) >= 4:
            _show, icnt = struct.unpack_from("<HH", payload, 0)
            need_il = 4 + icnt * ItemList._ENTRY_STRIDE
            if icnt == 0 and len(payload) >= 4:
                il = ItemList.parse(payload)
                self.items = list(il.items)
                return self
            if icnt > 0 and len(payload) >= need_il:
                il = ItemList.parse(payload)
                if len(il.items) == icnt:
                    self.items = list(il.items)
                    return self
        p = BasePacket(payload)
        try:
            n = p.read_ushort()
            if n <= 0 or n > 500:
                return self
            for _ in range(n):
                if p.remaining() < 2:
                    break
                mod = p.read_ushort()
                if mod == 3:
                    if p.remaining() >= 4:
                        self.items.append((p.read_int(), 0, 0))
                    continue
                if p.remaining() < ItemList._ENTRY_STRIDE:
                    break
                p.read_ushort()  # type1
                oid = p.read_int()
                iid = p.read_int()
                cnt = p.read_int()
                self.items.append((oid, iid, cnt))
                p.read_bytes(cls._ROW_TAIL)
        except Exception:
            pass
        return self
