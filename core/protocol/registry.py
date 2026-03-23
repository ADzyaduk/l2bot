"""
Packet opcode registry per chronicle.

Maps opcode integers to packet class names (strings, imported lazily).
Unknown opcodes are passed through transparently.

Chronicle ordering: c1 < c2 < c3 < c4 < interlude < c5 < gracia < h5
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.protocol.base_packet import BasePacket

# ---------------------------------------------------------------------- #
# Interlude (CT2.4) — primary target
# ---------------------------------------------------------------------- #

INTERLUDE_SERVER_OPCODES: dict[int, str] = {
    # Login Server packets (same on all servers)
    0x00: "SC_Init",
    0x01: "SC_LoginFail",
    0x03: "SC_AccountKicked",
    0x0B: "SC_ServerList",
    0x07: "SC_PlayFail",
    0x08: "SC_PlayOk",
    # Game Server packets — Teon/Elmorelab Interlude opcode table
    # NOTE: These are SESSION-2 observed opcodes only. Teon uses per-session
    # XOR scrambling so these values are WRONG for other sessions.
    # OpcodeDetector (core/protocol/opcode_detector.py) handles dynamic detection.
    # Kept here only for human-readable log labels in packet sniffer output.
    0x69: "SC_CharList",        # 329 bytes, appears on connection
    0x6F: "SC_CharSelected",    # 296 bytes, character enters world
    0x61: "SC_UserInfo",        # 468 bytes, own character full info
    0x6C: "SC_NpcInfo",         # 187 bytes, NPC/mob appeared (bulk on login)
    0x7B: "SC_MoveToPoint",     # 24 bytes, frequent entity movement
    0x17: "SC_StatusUpdate",    # 8 bytes, HP/MP/CP/EXP update
    0x7E: "SC_SkillList",       # 559 bytes, appears on login
    0x22: "SC_SystemMessage",
    0x1B: "SC_PickupItem",
    0x05: "SC_LogoutOk",
    0x14: "SC_LeaveWorld",
    0x2E: "SC_Say2",
    0x74: "SC_ValidatePosition", # 20 bytes, periodic position sync
    0x57: "SC_StopMove",         # 4 bytes, frequent
    0x5F: "SC_ChangeWaitType",   # 0 bytes (sit/stand toggle?)
    0x68: "SC_Die",              # 4 bytes
    0x84: "SC_ExBrExtraUserInfo",      # varies
    0x3D: "SC_TargetSelected",   # 16 bytes
    0x76: "SC_AutoAttackStart",  # 32 bytes
    0x1A: "SC_SpawnItem",        # 20 bytes, item on ground
    0x1E: "SC_StatusUpdate2",    # 4-20 bytes
    0x32: "SC_ExPartyInfo",      # ~36 bytes
    0x30: "SC_ExCharInfo",       # ~80 bytes, other players
    0x5D: "SC_ExUseSharedGroupItem",
    0x54: "SC_ExShowBaseAttributeCancel",
    0x56: "SC_ExStopMove",
    0x50: "SC_ExEnchantSkillInfo",
    0x9E: "SC_ExReceiveShowPostFriend",
    0xDC: "SC_ExNpcHtmlMessage",
    0xD8: "SC_ExSetCompassZoneCode",
    0x9D: "SC_ExReplaceItemFromPet",
    0x89: "SC_ExStorageMaxCount",
    0x80: "SC_ExOlympiadMatchList",
    0x7C: "SC_ExAutoSoulShot",
    0x77: "SC_ExBrProductInfo",
    0xFA: "SC_ExEscapeScene",
    0x51: "SC_ExUseItem2",
}

INTERLUDE_CLIENT_OPCODES: dict[int, str] = {
    0x00: "CS_Logout",
    0x01: "CS_MoveBackwardToLocation",
    0x03: "CS_RequestCharSelect",
    0x04: "CS_Action",            # right-click: target + interact/attack
    0x07: "CS_RequestDeleteChar",
    0x08: "CS_AuthLogin",         # game server auth (play_ok tokens)
    0x09: "CS_CharSelected",
    0x0A: "CS_AttackRequest",     # forced attack (Ctrl+click)
    0x2F: "CS_RequestActionAttack",  # actionId=16, real Teon attack command
    0x0D: "CS_RequestGMList",
    0x0F: "CS_MoveBackwardToLocation2",
    0x10: "CS_ValidatePosition",
    0x37: "CS_RequestTargetCancel",
    0x38: "CS_Say2",              # chat
    0x39: "CS_RequestMagicSkillUse",
    0x45: "CS_RequestActionUse",  # sit/stand, walk/run, etc.
    0x46: "CS_RequestDropItem",
    0x48: "CS_RequestGetItem",    # pick up item from ground
    0x59: "CS_RequestBypassToServer",  # NPC dialog
    0x5C: "CS_RequestEnterWorld",
    0x9D: "CS_RequestPing",       # keepalive
    0xD0: "CS_RequestEx",
}

CHRONICLES: dict[str, dict] = {
    "interlude": {
        "server": INTERLUDE_SERVER_OPCODES,
        "client": INTERLUDE_CLIENT_OPCODES,
        "has_xor_layer": False,
        "blowfish_default_key": "6B60CB5B82CE90B1CC2B6C556C6C6C6C",
    },
    # h5 and c4 will be added later with their delta opcode maps
}

_active_chronicle = "interlude"


def set_chronicle(name: str) -> None:
    global _active_chronicle
    if name not in CHRONICLES:
        raise ValueError(f"Unknown chronicle: {name!r}. Known: {list(CHRONICLES)}")
    _active_chronicle = name


def get_server_packet_name(opcode: int) -> str:
    return CHRONICLES[_active_chronicle]["server"].get(opcode, f"Unknown_S_{opcode:#04x}")


def get_client_packet_name(opcode: int) -> str:
    return CHRONICLES[_active_chronicle]["client"].get(opcode, f"Unknown_C_{opcode:#04x}")


def get_blowfish_default_key() -> bytes:
    key_hex = CHRONICLES[_active_chronicle]["blowfish_default_key"]
    return bytes.fromhex(key_hex)


def has_xor_layer() -> bool:
    return CHRONICLES[_active_chronicle]["has_xor_layer"]
