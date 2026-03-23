"""
Client → Server packet builders for Lineage 2 Interlude (Teon / Elmorelab).

Each function returns (opcode, payload_bytes).
The opcode is passed separately to GameProxy.inject_to_server().

Teon client opcodes (confirmed from actual client traffic + l2-unlegits):
  0x01 = MoveBackwardToLocation  (28 bytes: destX/Y/Z + origX/Y/Z + moveMode)
  0x04 = Action (right-click)    (17 bytes: objectId(4) + origX/Y/Z(12) + actionId(1))
         First click = target, second click = interact/attack
  0x0A = AttackRequest           (17 bytes: objectId(4) + origX/Y/Z(12) + shiftFlag(1))
         Forced attack (Ctrl+click)
  0x37 = RequestTargetCancel     (4 bytes: unselect(4))
  0x39 = RequestMagicSkillUse    (9 bytes: skillId(4) + ctrl(4) + shift(1))
  0x45 = RequestActionUse        (9 bytes: actionId(4) + ctrl(4) + shift(1))
         actionId 0 = sit/stand, 1 = walk/run toggle
  0x48 = RequestGetItem (pickup) (20 bytes: objectId(4) + x/y/z(12) + unknown(4))

NOTE: Game server C2S packets have NO checksum (only login server uses checksums).
"""
import struct
from core.protocol.base_packet import BasePacket


def build_move(x: int, y: int, z: int, orig_x: int, orig_y: int, orig_z: int) -> tuple[int, bytes]:
    """Move to X,Y,Z from origin. Returns (opcode, payload).
    Format: destX/Y/Z + origX/Y/Z + moveMode(1=mouse click)."""
    p = BasePacket()
    p.write_int(x)
    p.write_int(y)
    p.write_int(z)
    p.write_int(orig_x)
    p.write_int(orig_y)
    p.write_int(orig_z)
    p.write_int(1)  # moveMode: 1 = mouse click movement
    return 0x01, p.to_bytes()


def build_action(object_id: int, orig_x: int = 0, orig_y: int = 0, orig_z: int = 0,
                 shift: bool = False) -> tuple[int, bytes]:
    """
    CS_Action (0x04) — right-click on object (target + interact).
    First click = target, second click = interact/attack.
    Format: objectId(D) + origX(D) + origY(D) + origZ(D) + actionId(C).
    actionId: 0 = normal click, 1 = shift-click.
    Returns (opcode, payload).
    """
    p = BasePacket()
    p.write_int(object_id)
    p.write_int(orig_x)
    p.write_int(orig_y)
    p.write_int(orig_z)
    p.write_byte(1 if shift else 0)  # actionId: byte, not int32
    return 0x04, p.to_bytes()


def build_action_use(action_id: int, ctrl: bool = False, shift: bool = False) -> tuple[int, bytes]:
    """
    RequestActionUse — action bar buttons.
    actionId 0 = sit/stand, 1 = walk/run toggle, etc.
    Teon opcode = 0x45 (confirmed from real client traffic).
    Format: actionId(int32) + ctrl(int32) + shift(byte).
    Returns (opcode, payload).
    """
    p = BasePacket()
    p.write_int(action_id)
    p.write_int(1 if ctrl else 0)
    p.write_byte(1 if shift else 0)
    return 0x45, p.to_bytes()


def build_attack(target_id: int, orig_x: int = 0, orig_y: int = 0, orig_z: int = 0) -> tuple[int, bytes]:
    """Attack target via CS_Action (right-click). Returns (opcode, payload).
    On L2, right-click on mob = target it first, then attack on second click.
    We send the same Action packet — server handles target/attack logic."""
    return build_action(target_id, orig_x, orig_y, orig_z)


def build_use_skill(skill_id: int, ctrl: bool = False, shift: bool = False) -> tuple[int, bytes]:
    """Use magic/skill. Returns (opcode, payload).
    Format: skillId(int32) + ctrl(int32) + shift(byte)."""
    p = BasePacket()
    p.write_int(skill_id)
    p.write_int(1 if ctrl else 0)
    p.write_byte(1 if shift else 0)
    return 0x39, p.to_bytes()


def build_force_attack() -> tuple[int, bytes]:
    """Attack current target via opcode 0x2F with actionId=16.
    Confirmed from real Teon client traffic: plain=2f100000000000000000.
    Same format as RequestActionUse: actionId(int32) + ctrl(int32) + shift(byte)."""
    p = BasePacket()
    p.write_int(16)   # actionId = 16 (attack)
    p.write_int(0)    # ctrl = 0
    p.write_byte(0)   # shift = 0
    return 0x2F, p.to_bytes()


def build_cancel_target() -> tuple[int, bytes]:
    """Cancel current target. Standard L2J opcode 0x37."""
    p = BasePacket()
    p.write_int(0)  # unselect flag
    return 0x37, p.to_bytes()


def build_get_item(item_object_id: int, x: int, y: int, z: int) -> tuple[int, bytes]:
    """Pick up item from ground. Teon format: x/y/z + objectId + padding.
    Confirmed from real client traffic: 0x48 with 20 bytes."""
    p = BasePacket()
    p.write_int(x)
    p.write_int(y)
    p.write_int(z)
    p.write_int(item_object_id)
    p.write_int(0)  # unknown padding
    return 0x48, p.to_bytes()
