"""PartySmallWindow* parsers and World party + StatusUpdate merge."""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.packets.server import (
    ATTR_CUR_HP,
    ATTR_MAX_HP,
    PartySmallWindowAdd,
    PartySmallWindowAll,
    PartySmallWindowDelete,
    StatusUpdate,
)
from core.protocol.base_packet import BasePacket
from engine.world import World


def _member_bytes() -> bytes:
    p = BasePacket()
    p.write_string("Tank")
    p.write_int(0x11223344)
    p.write_int(3)  # class id
    p.write_int(80)
    p.write_int(100)
    p.write_int(40)
    p.write_int(50)
    p.write_int(10)
    p.write_int(20)  # max cp
    p.write_int(15)  # level
    return p.to_bytes()


def test_party_small_window_all_parse() -> None:
    p = BasePacket()
    p.write_int(1)
    p.write_bytes(_member_bytes())
    pkt = PartySmallWindowAll.parse(p.to_bytes())
    assert pkt.declared_count == 1
    assert len(pkt.members) == 1
    m = pkt.members[0]
    assert m.name == "Tank"
    assert m.object_id == 0x11223344
    assert m.cur_hp == 80 and m.max_hp == 100
    assert m.cur_mp == 40 and m.max_mp == 50
    assert m.level == 15


def test_party_small_window_all_count_zero_clears_declared() -> None:
    p = BasePacket()
    p.write_int(0)
    pkt = PartySmallWindowAll.parse(p.to_bytes())
    assert pkt.declared_count == 0
    assert pkt.members == []


def test_party_small_window_add() -> None:
    pkt = PartySmallWindowAdd.parse(_member_bytes())
    assert pkt.member is not None
    assert pkt.member.name == "Tank"


def test_party_small_window_delete() -> None:
    pkt = PartySmallWindowDelete.parse(b"\x44\x33\x22\x11")
    assert pkt.object_id == 0x11223344


def test_world_party_and_status_update() -> None:
    w = World()
    pkt = PartySmallWindowAdd.parse(_member_bytes())
    assert pkt.member
    w.on_party_small_window_add(pkt.member)
    oid = pkt.member.object_id
    su = StatusUpdate()
    su.object_id = oid
    su.attrs = {ATTR_CUR_HP: 1, ATTR_MAX_HP: 999}
    w.on_status_update(su)
    assert w.party_members[oid].cur_hp == 1
    assert w.party_members[oid].max_hp == 999
    w.on_party_small_window_delete(oid)
    assert oid not in w.party_members
