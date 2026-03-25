"""Test PartyProfile JSON serialization and PartySmallWindowUpdate handling."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.packets.server import PartyMemberInfo, PartySmallWindowUpdate
from engine.party_profile import PartyHealRule, PartyProfile, load_party_profile, save_party_profile
from engine.world import World


def test_party_profile_roundtrip():
    prof = PartyProfile(
        enabled=True,
        rules=[
            PartyHealRule(kind="heal", skill_id=1217, hp_below_pct=60.0, cooldown_sec=1.5),
            PartyHealRule(kind="mana", skill_id=1013, mp_below_pct=40.0),
            PartyHealRule(kind="buff", skill_id=1204, rebuff_if_missing=True, interval_sec=1200),
        ],
        heal_self_first=True,
        self_hp_critical_pct=25.0,
    )

    d = prof.to_dict()
    restored = PartyProfile.from_dict(d)

    assert restored.enabled is True
    assert len(restored.rules) == 3
    assert restored.rules[0].kind == "heal"
    assert restored.rules[0].skill_id == 1217
    assert restored.rules[0].hp_below_pct == 60.0
    assert restored.rules[1].kind == "mana"
    assert restored.rules[2].kind == "buff"
    assert restored.rules[2].rebuff_if_missing is True
    assert restored.heal_self_first is True
    assert restored.self_hp_critical_pct == 25.0


def test_party_profile_save_load(tmp_path: Path):
    prof = PartyProfile(
        rules=[PartyHealRule(kind="heal", skill_id=1217, hp_below_pct=50.0)],
    )
    p = tmp_path / "party.json"
    save_party_profile(prof, path=p)

    loaded = load_party_profile(path=p)
    assert len(loaded.rules) == 1
    assert loaded.rules[0].skill_id == 1217
    assert loaded.rules[0].hp_below_pct == 50.0


def test_party_profile_load_missing_file(tmp_path: Path):
    p = tmp_path / "nonexistent.json"
    prof = load_party_profile(path=p)
    assert prof.enabled is True
    assert len(prof.rules) == 0


def test_party_profile_empty_dict():
    prof = PartyProfile.from_dict({})
    assert prof.enabled is True
    assert len(prof.rules) == 0
    assert prof.heal_self_first is True


def test_party_small_window_update():
    """Verify PartySmallWindowUpdate updates party member HP/MP in World."""
    w = World()

    # Add party member via PartySmallWindowAdd
    m = PartyMemberInfo(
        object_id=0x200, name="Ally",
        cur_hp=100, max_hp=200, cur_mp=50, max_mp=100,
    )
    w.on_party_small_window_add(m)
    assert w.party_members[0x200].cur_hp == 100

    # Simulate update
    pkt = PartySmallWindowUpdate()
    pkt.object_id = 0x200
    pkt.cur_hp = 50
    pkt.max_hp = 200
    pkt.cur_mp = 30
    pkt.max_mp = 100
    pkt.cur_cp = 0
    pkt.max_cp = 0
    w.on_party_small_window_update(pkt)

    assert w.party_members[0x200].cur_hp == 50
    assert w.party_members[0x200].cur_mp == 30


def test_party_small_window_update_unknown_member():
    """Update for unknown member should be silently ignored."""
    w = World()
    pkt = PartySmallWindowUpdate()
    pkt.object_id = 0x999
    pkt.cur_hp = 50
    pkt.max_hp = 200
    w.on_party_small_window_update(pkt)
    assert 0x999 not in w.party_members
