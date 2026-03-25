"""Tests for ItemList, SkillCoolTime, AbnormalStatusUpdate parsers."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.packets.server import (
    AbnormalStatusUpdate,
    InventoryUpdate,
    ItemList,
    SkillCoolTime,
    MagicSkillLaunched,
    PartySpelled,
)
from engine.world import World


class TestItemList:
    def test_one_item_l2j_stride(self):
        body = struct.pack("<HH", 1, 1)
        body += struct.pack("<Hiii", 2, 0x10001, 57, 5)
        body += b"\x00" * (ItemList._ENTRY_STRIDE - 14)
        pkt = ItemList.parse(body)
        assert pkt.show_window is True
        assert len(pkt.items) == 1
        assert pkt.items[0] == (0x10001, 57, 5)


class TestInventoryUpdate:
    def test_full_list_same_as_itemlist(self):
        body = struct.pack("<HH", 1, 1)
        body += struct.pack("<Hiii", 2, 0x10001, 57, 5)
        body += b"\x00" * (ItemList._ENTRY_STRIDE - 14)
        pkt = InventoryUpdate.parse(body)
        assert pkt.items == [(0x10001, 57, 5)]

    def test_delta_remove_mod3(self):
        body = struct.pack("<H", 1) + struct.pack("<H", 3) + struct.pack("<i", 0x11223344)
        pkt = InventoryUpdate.parse(body)
        assert pkt.items == [(0x11223344, 0, 0)]

    def test_world_merge_remove_and_update(self):
        w = World()
        w.inventory_by_object[100] = (57, 10)
        w.on_inventory_update(InventoryUpdate.parse(
            struct.pack("<H", 1) + struct.pack("<H", 3) + struct.pack("<i", 100)
        ))
        assert 100 not in w.inventory_by_object
        w.inventory_by_object[200] = (57, 1)
        row = struct.pack("<H", 1) + struct.pack("<H", 1)
        row += struct.pack("<Hiii", 2, 200, 57, 3)
        row += b"\x00" * (ItemList._ENTRY_STRIDE - 14)
        w.on_inventory_update(InventoryUpdate.parse(row))
        assert w.inventory_by_object[200] == (57, 3)


class TestSkillCoolTime:
    def test_count_and_rows(self):
        body = struct.pack("<i", 2)
        body += struct.pack("<iii", 10, 3000, 5000)
        body += struct.pack("<iii", 20, 0, 1000)
        pkt = SkillCoolTime.parse(body)
        assert len(pkt.rows) == 2
        assert pkt.rows[0][0] == 10 and pkt.rows[0][1] == 3000


class TestAbnormalStatusUpdate:
    def test_h_count_first(self):
        body = struct.pack("<H", 1)
        body += struct.pack("<ihI", 1200, 3, 600000)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == 0
        assert len(pkt.effects) == 1
        assert pkt.effects[0][0] == 1200

    def test_object_id_prefix(self):
        body = struct.pack("<iH", 0x7EABCD00, 1)
        body += struct.pack("<ihI", 99, 1, 0)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == 0x7EABCD00
        assert len(pkt.effects) == 1
        assert pkt.effects[0][0] == 99

    def test_oid_dword_count_layout(self):
        body = struct.pack("<ii", 0x48ABCDEF, 2)
        body += struct.pack("<ihI", 10, 1, 0)
        body += struct.pack("<ihI", 91, 1, 0)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == 0x48ABCDEF
        assert {e[0] for e in pkt.effects} == {10, 91}

    def test_teon_oid_dword_count_one_effect_golden(self):
        """Teon-style SC_AbnormalStatusUpdate: int32 objectId + int32 count + effects (ihI rows)."""
        body = struct.pack("<ii", 0x12345678, 1)
        body += struct.pack("<ihI", 100, 1, 3600)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == 0x12345678
        assert pkt.effects == [(100, 1, 3600)]

    def test_dword_count_layout(self):
        body = struct.pack("<i", 1) + struct.pack("<ihI", 500, 2, 100)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == 0
        assert len(pkt.effects) == 1
        assert pkt.effects[0][0] == 500

    def test_empty_abnormal_6b_oid(self):
        oid = 0x48604547
        body = struct.pack("<iH", oid, 0)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == oid
        assert pkt.effects == []
        assert pkt.explicit_empty is True

    def test_empty_abnormal_8b_ih_pad(self):
        oid = 0x48604547
        body = struct.pack("<iH", oid, 0) + b"\x00\x00"
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == oid
        assert pkt.effects == []
        assert pkt.explicit_empty is True

    def test_empty_abnormal_8b_ii_count(self):
        oid = 0x48604547
        body = struct.pack("<ii", oid, 0)
        pkt = AbnormalStatusUpdate.parse(body)
        assert pkt.object_id == oid
        assert pkt.effects == []
        assert pkt.explicit_empty is True

    def test_all_zero_8b_not_explicit_empty(self):
        pkt = AbnormalStatusUpdate.parse(b"\x00" * 8)
        assert not pkt.effects
        assert pkt.explicit_empty is False


class TestWorldAbnormalWipe:
    def test_non_explicit_empty_does_not_clear_buffs(self) -> None:
        w = World()
        w.me.object_id = 0x48
        w.on_abnormal_status_update(0x48, [(91, 1, 100)])
        assert 91 in w.abnormal_skill_ids_for_object(0x48)
        w.on_abnormal_status_update(0x48, [], explicit_empty=False)
        assert 91 in w.abnormal_skill_ids_for_object(0x48)

    def test_explicit_empty_clears(self) -> None:
        w = World()
        w.me.object_id = 0x48
        w.on_abnormal_status_update(0x48, [(91, 1, 100)])
        w.on_abnormal_status_update(0x48, [], explicit_empty=True)
        assert w.abnormal_skill_ids_for_object(0x48) == set()


class TestWorldSkillListBuff:
    def test_buff_present_via_skill_list(self):
        w = World()
        assert w.buff_present_via_skill_list(91) is None
        w.on_skill_list([(91, 1, False)])
        assert w.buff_present_via_skill_list(91) is True
        w.on_skill_list([(10, 1, False)])
        assert w.buff_present_via_skill_list(91) is False
        w.on_skill_list([(91, 0, False)])
        assert w.buff_present_via_skill_list(91) is False

    def test_buff_present_merged_self(self):
        w = World()
        w.me.object_id = 0x10
        assert w.buff_present_merged_self(91) is None
        w.on_skill_list([(91, 1, False)])
        assert w.buff_present_merged_self(91) is None
        w.on_magic_skill_launched(
            MagicSkillLaunched(
                caster_id=0x10, target_id=0x10, skill_id=91, skill_level=1
            )
        )
        assert w.buff_present_merged_self(91) is True
        w.on_magic_skill_launched(
            MagicSkillLaunched(
                caster_id=0x10, target_id=0x10, skill_id=91, skill_level=0
            )
        )
        assert w.buff_present_merged_self(91) is False


class TestMagicSkillLaunched:
    def test_parse_teon_sample(self):
        # Log sample (32B) + z padding to 36B
        raw = bytes.fromhex(
            "ed9a2048ed9a20485b00000001000000d4140000401f00009b8f0000f9d70000"
        )
        raw = raw + b"\x00\x00\x00\x00"
        pkt = MagicSkillLaunched.parse(raw)
        assert pkt.caster_id == 0x48209AED
        assert pkt.target_id == 0x48209AED
        assert pkt.skill_id == 91
        assert pkt.skill_level == 1
        assert pkt.x == 0x8F9B
        assert pkt.y == 0xD7F9


class TestPartySpelled:
    def test_parse_one_member_one_buff(self):
        oid = 0x48ABCDEF
        body = struct.pack("<iH", oid, 1)
        body += struct.pack("<ihI", 1200, 2, 1800)
        pkt = PartySpelled.parse(body)
        assert pkt.object_id == oid
        assert pkt.effects == [(1200, 2, 1800)]


class TestWorldPartySpelled:
    def test_party_spelled_merges_buff_ids(self):
        w = World()
        w.on_party_spelled(0x200, [(50, 1, 100)])
        assert w.abnormal_skill_ids_for_object(0x200) == {50}


class TestPickAutoCombatTarget:
    def test_retains_current_within_distance(self):
        from engine.world import Npc

        w = World()
        w.me.x, w.me.y, w.me.z = 0, 0, 0
        w.npcs[100] = Npc(
            object_id=100,
            npc_type_id=501 + 1_000_000,
            name="",
            title="",
            x=50,
            y=0,
            z=0,
            heading=0,
            is_attackable=True,
        )
        w.npcs[101] = Npc(
            object_id=101,
            npc_type_id=502 + 1_000_000,
            name="",
            title="",
            x=500,
            y=0,
            z=0,
            heading=0,
            is_attackable=True,
        )
        a = w.pick_auto_combat_target(
            2000.0,
            prefer_aggro=False,
            retain_target_oid=101,
            retain_max_dist=800.0,
            npc_blacklist=frozenset(),
            attack_only_whitelist=False,
            npc_whitelist=frozenset(),
            target_z_range_max=0.0,
            skip_summoned=False,
            never_attack_oids=frozenset(),
        )
        assert a is not None and a.object_id == 101

    def test_prefers_aggro_when_closer_non_aggro_exists(self):
        from engine.world import Npc

        w = World()
        w.me.x, w.me.y, w.me.z = 0, 0, 0
        w.npcs[10] = Npc(
            object_id=10,
            npc_type_id=1 + 1_000_000,
            name="",
            title="",
            x=100,
            y=0,
            z=0,
            heading=0,
            is_attackable=True,
        )
        w.npcs[11] = Npc(
            object_id=11,
            npc_type_id=2 + 1_000_000,
            name="",
            title="",
            x=300,
            y=0,
            z=0,
            heading=0,
            is_attackable=True,
        )
        w.register_attacker_on_me(11)
        picked = w.pick_auto_combat_target(
            2000.0,
            prefer_aggro=True,
            retain_target_oid=0,
            retain_max_dist=0.0,
            npc_blacklist=frozenset(),
            attack_only_whitelist=False,
            npc_whitelist=frozenset(),
            target_z_range_max=0.0,
            skip_summoned=False,
            never_attack_oids=frozenset(),
        )
        assert picked is not None and picked.object_id == 11

    def test_attack_only_whitelist_empty_does_not_block_everything(self):
        """UI mistake: whitelist-only with empty list must not filter out all NPCs."""
        from engine.world import Npc

        w = World()
        w.me.x, w.me.y, w.me.z = 0, 0, 0
        w.npcs[7] = Npc(
            object_id=7,
            npc_type_id=99 + 1_000_000,
            name="",
            title="",
            x=80,
            y=0,
            z=0,
            heading=0,
            is_attackable=True,
        )
        picked = w.pick_auto_combat_target(
            2000.0,
            prefer_aggro=False,
            retain_target_oid=0,
            retain_max_dist=0.0,
            npc_blacklist=frozenset(),
            attack_only_whitelist=True,
            npc_whitelist=frozenset(),
            target_z_range_max=0.0,
            skip_summoned=False,
            never_attack_oids=frozenset(),
        )
        assert picked is not None and picked.object_id == 7
