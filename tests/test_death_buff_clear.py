"""Test that buffs are cleared on death for self and party members."""
from __future__ import annotations

from core.packets.server import Die, UserInfo, PartyMemberInfo
from engine.world import World


def _user_info(oid: int) -> UserInfo:
    return UserInfo(object_id=oid, cur_hp=200, max_hp=300, cur_mp=100, max_mp=150, name="TestChar")


def test_self_death_clears_abnormal_buffs():
    w = World()
    w.on_user_info(_user_info(0x100))

    # Simulate buffs present
    w.on_abnormal_status_update(0x100, [(91, 1, 1200), (274, 1, 600)])
    assert 91 in w.abnormal_buff_skill_ids
    assert 274 in w.abnormal_buff_skill_ids
    assert 0x100 in w.abnormal_buffs_by_object

    # Die
    pkt = Die()
    pkt.object_id = 0x100
    w.on_die(pkt)

    # Buffs should be cleared
    assert len(w.abnormal_buff_skill_ids) == 0
    assert 0x100 not in w.abnormal_buffs_by_object


def test_party_member_death_clears_buffs():
    w = World()
    w.on_user_info(_user_info(0x100))

    # Add party member
    m = PartyMemberInfo(object_id=0x200, name="Ally", cur_hp=100, max_hp=200, cur_mp=50, max_mp=100)
    w.on_party_small_window_add(m)

    # Simulate party member buffs via PartySpelled
    w.on_party_spelled(0x200, [(91, 1, 1200)])
    assert 91 in w.abnormal_buffs_by_object.get(0x200, set())

    # Party member dies
    pkt = Die()
    pkt.object_id = 0x200
    w.on_die(pkt)

    # Party member buffs should be cleared
    assert 0x200 not in w.abnormal_buffs_by_object


def test_self_death_does_not_clear_party_member_buffs():
    w = World()
    w.on_user_info(_user_info(0x100))

    # Party member has buffs
    w.on_party_spelled(0x200, [(91, 1, 1200)])
    # Self has buffs
    w.on_abnormal_status_update(0x100, [(274, 1, 600)])

    # Self dies
    pkt = Die()
    pkt.object_id = 0x100
    w.on_die(pkt)

    # Self buffs cleared
    assert len(w.abnormal_buff_skill_ids) == 0
    assert 0x100 not in w.abnormal_buffs_by_object
    # Party member buffs intact
    assert 91 in w.abnormal_buffs_by_object.get(0x200, set())


def test_npc_death_does_not_affect_self_buffs():
    w = World()
    w.on_user_info(_user_info(0x100))
    w.on_abnormal_status_update(0x100, [(91, 1, 1200)])

    # NPC dies
    pkt = Die()
    pkt.object_id = 0x300
    w.on_die(pkt)

    # Self buffs intact
    assert 91 in w.abnormal_buff_skill_ids
