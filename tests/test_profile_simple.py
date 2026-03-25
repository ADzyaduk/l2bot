"""Unit tests for ui.profile_simple helpers."""
from __future__ import annotations

from engine.buff_profile import BuffRule
from engine.combat_profile import CombatRule
from ui.profile_simple import (
    buff_filtered_indices,
    buff_rule_is_party_manual,
    buff_rule_is_self,
    combat_when_summary,
    interval_display_minutes,
    interval_sec_from_minutes,
)


def test_interval_minutes_roundtrip() -> None:
    assert interval_sec_from_minutes(20) == 20 * 60.0
    assert interval_display_minutes(1200.0) == "20"


def test_buff_filters() -> None:
    rules = [
        BuffRule(skill_id=1, target_mode="self"),
        BuffRule(skill_id=2, target_mode="manual", target_object_id=100),
        BuffRule(skill_id=3, target_mode="manual", target_object_id=0),
    ]
    assert buff_rule_is_self(rules[0])
    assert not buff_rule_is_self(rules[1])
    assert buff_rule_is_party_manual(rules[1])
    assert not buff_rule_is_party_manual(rules[2])
    assert buff_filtered_indices(rules, party=False) == [0]
    assert buff_filtered_indices(rules, party=True) == [1]


def test_combat_when_summary() -> None:
    r = CombatRule(
        kind="skill",
        skill_id=10,
        only_in_combat=True,
        hp_below_pct=40.0,
    )
    s = combat_when_summary(r)
    assert "in combat" in s
    assert "HP<40" in s
