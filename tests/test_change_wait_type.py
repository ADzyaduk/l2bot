"""SC_ChangeWaitType parse + World sit flag mapping."""
from engine.world import World
from core.packets.server import ChangeWaitType


def test_change_wait_type_parse_eight_bytes():
    # objectId 0x4830C231 LE + wait_type 0
    p = bytes([0x31, 0xC2, 0x30, 0x48, 0x00, 0x00, 0x00, 0x00])
    c = ChangeWaitType.parse(p)
    assert c.object_id == 0x4830C231
    assert c.wait_type == 0


def test_world_change_wait_type_acis_style():
    w = World()
    w.me.object_id = 0x100
    w.on_change_wait_type(0x100, 0, sit_raw=0)
    assert w.me.me_sitting is True
    w.on_change_wait_type(0x100, 1, sit_raw=0)
    assert w.me.me_sitting is False


def test_world_change_wait_type_mobius_style():
    w = World()
    w.me.object_id = 0x100
    w.on_change_wait_type(0x100, 1, sit_raw=1)
    assert w.me.me_sitting is True
    w.on_change_wait_type(0x100, 0, sit_raw=1)
    assert w.me.me_sitting is False


def test_world_change_wait_type_ignores_other_objects():
    w = World()
    w.me.object_id = 0x100
    w.on_change_wait_type(0x200, 0, sit_raw=0)
    assert w.me.me_sitting is None
