"""
Party support profile: heal, mana restore, and buff rules for party members.
Persisted as JSON per character under config/characters/<slug>/party.json.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from engine.character_config import (
    legacy_party_profile_path,
    resolve_party_profile_read_path,
    resolve_party_profile_write_path,
)

log = logging.getLogger(__name__)

PartyRuleKind = Literal["heal", "mana", "buff"]

_MAGIC_SKILL_PAYLOAD_VALID = frozenset({"dcb", "ddd", "dcc"})
_SKILL_PACKET_VALID = frozenset({"39", "2f"})


def _normalize_payload(value: str) -> str:
    v = (value or "ddd").strip().lower()
    return v if v in _MAGIC_SKILL_PAYLOAD_VALID else "ddd"


def _normalize_packet(value: str) -> str:
    v = (value or "2f").strip().lower()
    if v in ("0x39", "0x2f"):
        v = v[2:]
    return v if v in _SKILL_PACKET_VALID else "2f"


@dataclass
class PartyHealRule:
    enabled: bool = True
    kind: PartyRuleKind = "heal"
    skill_id: int = 0
    # For heal: cast when party member HP < this %
    hp_below_pct: float = 70.0
    # For mana: cast when party member MP < this %
    mp_below_pct: float = 50.0
    cooldown_sec: float = 1.0
    # Lower = higher priority
    priority: int = 0
    # For buff rules:
    rebuff_if_missing: bool = False
    check_buff_skill_id: int = 0
    interval_sec: float = 1200.0
    # Shift-click to target ally (avoids starting attack)
    target_shift_click: bool = True
    # RequestMagicSkillUse ctrl/shift flags
    skill_force_ctrl: bool = False
    skill_force_shift: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PartyHealRule":
        kind = d.get("kind", "heal")
        if kind not in ("heal", "mana", "buff"):
            kind = "heal"
        return cls(
            enabled=bool(d.get("enabled", True)),
            kind=kind,  # type: ignore[arg-type]
            skill_id=int(d.get("skill_id", 0)),
            hp_below_pct=float(d.get("hp_below_pct", 70.0)),
            mp_below_pct=float(d.get("mp_below_pct", 50.0)),
            cooldown_sec=float(d.get("cooldown_sec", 1.0)),
            priority=int(d.get("priority", 0)),
            rebuff_if_missing=bool(d.get("rebuff_if_missing", False)),
            check_buff_skill_id=int(d.get("check_buff_skill_id", 0)),
            interval_sec=float(d.get("interval_sec", 1200.0)),
            target_shift_click=bool(d.get("target_shift_click", True)),
            skill_force_ctrl=bool(d.get("skill_force_ctrl", False)),
            skill_force_shift=bool(d.get("skill_force_shift", False)),
        )


@dataclass
class PartyProfile:
    enabled: bool = True
    rules: list[PartyHealRule] = field(default_factory=list)
    # Prioritize self-heal when own HP is critical
    heal_self_first: bool = True
    self_hp_critical_pct: float = 30.0
    # How often to check party member HP/MP
    poll_interval_sec: float = 0.5
    # Delay after switching target before casting
    target_switch_delay_sec: float = 0.3
    # RequestMagicSkillUse body layout
    magic_skill_payload: str = "ddd"
    # C2S opcode: "39" or "2f"
    party_skill_packet: str = "2f"
    # Pause party heal while auto-combat is in kill loop
    pause_while_combat_engaged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rules": [r.to_dict() for r in self.rules],
            "heal_self_first": self.heal_self_first,
            "self_hp_critical_pct": self.self_hp_critical_pct,
            "poll_interval_sec": self.poll_interval_sec,
            "target_switch_delay_sec": self.target_switch_delay_sec,
            "magic_skill_payload": self.magic_skill_payload,
            "party_skill_packet": self.party_skill_packet,
            "pause_while_combat_engaged": self.pause_while_combat_engaged,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PartyProfile":
        rules_raw = d.get("rules") or []
        rules = [PartyHealRule.from_dict(x) for x in rules_raw if isinstance(x, dict)]
        return cls(
            enabled=bool(d.get("enabled", True)),
            rules=rules,
            heal_self_first=bool(d.get("heal_self_first", True)),
            self_hp_critical_pct=float(d.get("self_hp_critical_pct", 30.0)),
            poll_interval_sec=float(d.get("poll_interval_sec", 0.5)),
            target_switch_delay_sec=float(d.get("target_switch_delay_sec", 0.3)),
            magic_skill_payload=_normalize_payload(str(d.get("magic_skill_payload", "ddd"))),
            party_skill_packet=_normalize_packet(str(d.get("party_skill_packet", "2f"))),
            pause_while_combat_engaged=bool(d.get("pause_while_combat_engaged", False)),
        )


def load_party_profile(
    path: Path | None = None,
    *,
    character_name: str | None = None,
    root: Path | None = None,
) -> PartyProfile:
    r = root or Path(__file__).resolve().parents[1]
    if path is not None:
        p = path
    elif character_name is None:
        p = legacy_party_profile_path(r)
    else:
        p, _ = resolve_party_profile_read_path(character_name=character_name, root=r)
    if not p.is_file():
        return PartyProfile()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return PartyProfile.from_dict(data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Failed to load party profile %s: %s", p, exc)
        return PartyProfile()


def save_party_profile(
    profile: PartyProfile,
    path: Path | None = None,
    *,
    character_name: str | None = None,
    root: Path | None = None,
) -> None:
    r = root or Path(__file__).resolve().parents[1]
    if path is not None:
        p = path
    else:
        p = resolve_party_profile_write_path(character_name=character_name, root=r)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    log.info("Saved party profile: %s (%d rules)", p, len(profile.rules))
