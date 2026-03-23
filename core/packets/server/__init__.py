"""
Server → Client packet parsers for Lineage 2 Interlude.

Each class parses a raw payload (bytes after opcode, before checksum)
using BasePacket cursor helpers.
"""
from dataclasses import dataclass, field
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
            p.read_byte()       # isSummoned
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
