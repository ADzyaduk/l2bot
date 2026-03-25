"""Small helpers for simple Buff / Auto combat UI (filters, display, minutes)."""
from __future__ import annotations

from engine.buff_profile import BuffRule
from engine.combat_profile import CombatRule


def buff_rule_is_self(r: BuffRule) -> bool:
    return r.target_mode == "self"


def buff_rule_is_party_manual(r: BuffRule) -> bool:
    return r.target_mode == "manual" and r.target_object_id > 0


def buff_filtered_indices(rules: list[BuffRule], *, party: bool) -> list[int]:
    if party:
        return [i for i, r in enumerate(rules) if buff_rule_is_party_manual(r)]
    return [i for i, r in enumerate(rules) if buff_rule_is_self(r)]


def interval_display_minutes(interval_sec: float) -> str:
    if interval_sec <= 0:
        return "0"
    m = interval_sec / 60.0
    if abs(m - round(m)) < 0.05:
        return str(int(round(m)))
    return f"{m:.1f}"


def interval_sec_from_minutes(minutes: float) -> float:
    return max(60.0, float(minutes) * 60.0)


def combat_when_summary(r: CombatRule) -> str:
    parts: list[str] = []
    if r.only_in_combat:
        parts.append("in combat")
    else:
        parts.append("out of combat ok")
    if r.hp_below_pct > 0:
        parts.append(f"HP<{r.hp_below_pct:g}%")
    if r.mp_below_pct > 0:
        parts.append(f"MP<{r.mp_below_pct:g}%")
    if r.hp_min_pct > 0:
        parts.append(f"HP≥{r.hp_min_pct:g}%")
    if r.mp_min_pct > 0:
        parts.append(f"MP≥{r.mp_min_pct:g}%")
    if r.cooldown_sec > 0:
        parts.append(f"CD {r.cooldown_sec:g}s")
    if r.rebuff_missing_skill_id > 0:
        parts.append("rebuff gate")
    if r.fire_before_first_attack:
        parts.append("before 1st hit")
    if not parts:
        return "always"
    return ", ".join(parts)
