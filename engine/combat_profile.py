"""
Combat rotation profile: ordered rules (skill / item template id) with thresholds.
Recovery (sit / HP / MP) and loot settings. Persisted as JSON.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from engine.buff_profile import (
    default_buff_profile_path,
    normalize_magic_skill_payload,
    normalize_target_cancel_payload,
)

log = logging.getLogger(__name__)

RuleType = Literal["skill", "item"]


@dataclass
class CombatRule:
    kind: RuleType
    skill_id: int = 0
    item_id: int = 0
    hp_below_pct: float = 0.0
    mp_below_pct: float = 0.0
    # If > 0: require HP%% >= this (e.g. save big nukes until not critical).
    hp_min_pct: float = 0.0
    # If > 0: require MP%% >= this (e.g. Mortal Blow only with enough mana).
    mp_min_pct: float = 0.0
    only_in_combat: bool = True
    cooldown_sec: float = 0.0
    # If > 0: only fire when this buff skill id is absent from AbnormalStatusUpdate (rebuff).
    rebuff_missing_skill_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CombatRule":
        kind = d.get("kind", "skill")
        if kind not in ("skill", "item"):
            kind = "skill"
        return cls(
            kind=kind,
            skill_id=int(d.get("skill_id", 0)),
            item_id=int(d.get("item_id", 0)),
            hp_below_pct=float(d.get("hp_below_pct", 0)),
            mp_below_pct=float(d.get("mp_below_pct", 0)),
            hp_min_pct=float(d.get("hp_min_pct", 0)),
            mp_min_pct=float(d.get("mp_min_pct", 0)),
            only_in_combat=bool(d.get("only_in_combat", True)),
            cooldown_sec=float(d.get("cooldown_sec", 0)),
            rebuff_missing_skill_id=int(d.get("rebuff_missing_skill_id", 0)),
        )


@dataclass
class CombatProfile:
    rules: list[CombatRule] = field(default_factory=list)
    post_skill_delay: float = 0.35
    post_target_delay: float = 0.3
    # During combat: sit if HP below this, stand when HP reaches combat_stand_hp_pct
    combat_sit_hp_below_pct: float = 30.0
    combat_stand_hp_pct: float = 70.0
    # After kill: optional sit regen
    post_kill_sit_enabled: bool = True
    post_kill_sit_hp_below_pct: float = 50.0
    post_kill_stand_hp_pct: float = 80.0
    # If both > 0: while sitting, also wait until MP >= recovery_stand_mp_pct before standing
    recovery_sit_mp_below_pct: float = 0.0
    recovery_stand_mp_pct: float = 0.0
    recovery_max_wait_sec: float = 60.0
    # SC_ChangeWaitType second dword when your character is sitting: 0 = Acis-style Teon; 1 = some Mobius forks.
    recovery_change_wait_type_sit_raw: int = 0
    auto_loot: bool = True
    loot_range: float = 800.0
    # Do not sit for post-kill regen while target is a living attackable mob, or shortly after taking damage.
    never_sit_while_target: bool = True
    incoming_damage_sit_block_sec: float = 2.5
    # Kill loop timing (was hardcoded in BotEngine).
    kill_poll_tick_sec: float = 0.2
    kill_timeout_sec: float = 20.0
    reattack_interval_sec: float = 1.5
    reattack_action_sleep_sec: float = 0.12
    post_kill_spawn_wait_sec: float = 0.35
    post_kill_loot_item_delay_sec: float = 0.22
    post_kill_loot_after_sleep_sec: float = 0.2
    post_kill_recovery_after_stand_sec: float = 0.5
    between_targets_sleep_sec: float = 0.12
    idle_no_mobs_sleep_sec: float = 1.0
    open_combat_pre_loot_sleep_sec: float = 0.25
    idle_loot_item_delay_sec: float = 0.22
    # RequestTargetCancel (0x37) body after kill — WORD(0) vs DWORD(0); only used by auto-combat cancel_target.
    target_cancel_payload: str = "h"
    # RequestMagicSkillUse (0x39) for auto-combat rules — dcb typical Interlude client; buffs use buff profile.
    magic_skill_payload: str = "dcb"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": [r.to_dict() for r in self.rules],
            "post_skill_delay": self.post_skill_delay,
            "post_target_delay": self.post_target_delay,
            "combat_sit_hp_below_pct": self.combat_sit_hp_below_pct,
            "combat_stand_hp_pct": self.combat_stand_hp_pct,
            "post_kill_sit_enabled": self.post_kill_sit_enabled,
            "post_kill_sit_hp_below_pct": self.post_kill_sit_hp_below_pct,
            "post_kill_stand_hp_pct": self.post_kill_stand_hp_pct,
            "recovery_sit_mp_below_pct": self.recovery_sit_mp_below_pct,
            "recovery_stand_mp_pct": self.recovery_stand_mp_pct,
            "recovery_max_wait_sec": self.recovery_max_wait_sec,
            "recovery_change_wait_type_sit_raw": self.recovery_change_wait_type_sit_raw,
            "auto_loot": self.auto_loot,
            "loot_range": self.loot_range,
            "never_sit_while_target": self.never_sit_while_target,
            "incoming_damage_sit_block_sec": self.incoming_damage_sit_block_sec,
            "kill_poll_tick_sec": self.kill_poll_tick_sec,
            "kill_timeout_sec": self.kill_timeout_sec,
            "reattack_interval_sec": self.reattack_interval_sec,
            "reattack_action_sleep_sec": self.reattack_action_sleep_sec,
            "post_kill_spawn_wait_sec": self.post_kill_spawn_wait_sec,
            "post_kill_loot_item_delay_sec": self.post_kill_loot_item_delay_sec,
            "post_kill_loot_after_sleep_sec": self.post_kill_loot_after_sleep_sec,
            "post_kill_recovery_after_stand_sec": self.post_kill_recovery_after_stand_sec,
            "between_targets_sleep_sec": self.between_targets_sleep_sec,
            "idle_no_mobs_sleep_sec": self.idle_no_mobs_sleep_sec,
            "open_combat_pre_loot_sleep_sec": self.open_combat_pre_loot_sleep_sec,
            "idle_loot_item_delay_sec": self.idle_loot_item_delay_sec,
            "target_cancel_payload": self.target_cancel_payload,
            "magic_skill_payload": self.magic_skill_payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CombatProfile":
        rules_raw = d.get("rules") or []
        rules = [CombatRule.from_dict(x) for x in rules_raw if isinstance(x, dict)]
        return cls(
            rules=rules,
            post_skill_delay=float(d.get("post_skill_delay", 0.35)),
            post_target_delay=float(d.get("post_target_delay", 0.3)),
            combat_sit_hp_below_pct=float(d.get("combat_sit_hp_below_pct", 30)),
            combat_stand_hp_pct=float(d.get("combat_stand_hp_pct", 70)),
            post_kill_sit_enabled=bool(d.get("post_kill_sit_enabled", True)),
            post_kill_sit_hp_below_pct=float(d.get("post_kill_sit_hp_below_pct", 50)),
            post_kill_stand_hp_pct=float(d.get("post_kill_stand_hp_pct", 80)),
            recovery_sit_mp_below_pct=float(d.get("recovery_sit_mp_below_pct", 0)),
            recovery_stand_mp_pct=float(d.get("recovery_stand_mp_pct", 0)),
            recovery_max_wait_sec=float(d.get("recovery_max_wait_sec", 60)),
            recovery_change_wait_type_sit_raw=int(d.get("recovery_change_wait_type_sit_raw", 0)),
            auto_loot=bool(d.get("auto_loot", True)),
            loot_range=float(d.get("loot_range", 800)),
            never_sit_while_target=bool(d.get("never_sit_while_target", True)),
            incoming_damage_sit_block_sec=float(d.get("incoming_damage_sit_block_sec", 2.5)),
            kill_poll_tick_sec=float(d.get("kill_poll_tick_sec", 0.2)),
            kill_timeout_sec=float(d.get("kill_timeout_sec", 20.0)),
            reattack_interval_sec=float(d.get("reattack_interval_sec", 1.5)),
            reattack_action_sleep_sec=float(d.get("reattack_action_sleep_sec", 0.12)),
            post_kill_spawn_wait_sec=float(d.get("post_kill_spawn_wait_sec", 0.35)),
            post_kill_loot_item_delay_sec=float(d.get("post_kill_loot_item_delay_sec", 0.22)),
            post_kill_loot_after_sleep_sec=float(d.get("post_kill_loot_after_sleep_sec", 0.2)),
            post_kill_recovery_after_stand_sec=float(d.get("post_kill_recovery_after_stand_sec", 0.5)),
            between_targets_sleep_sec=float(d.get("between_targets_sleep_sec", 0.12)),
            idle_no_mobs_sleep_sec=float(d.get("idle_no_mobs_sleep_sec", 1.0)),
            open_combat_pre_loot_sleep_sec=float(d.get("open_combat_pre_loot_sleep_sec", 0.25)),
            idle_loot_item_delay_sec=float(d.get("idle_loot_item_delay_sec", 0.22)),
            target_cancel_payload=normalize_target_cancel_payload(str(d.get("target_cancel_payload", "h"))),
            magic_skill_payload=normalize_magic_skill_payload(str(d.get("magic_skill_payload", "dcb"))),
        )

    def mp_recovery_enabled(self) -> bool:
        return self.recovery_sit_mp_below_pct > 0 and self.recovery_stand_mp_pct > 0


def default_profile_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parents[1]
    return base / "config" / "autocombat.json"


def _migrate_target_cancel_from_buffs_json(prof: "CombatProfile", *, log_ok: bool) -> None:
    """Legacy: target_cancel_payload lived in buffs.json; now it belongs in autocombat.json."""
    try:
        bpath = default_buff_profile_path()
        if not bpath.is_file():
            return
        bd = json.loads(bpath.read_text(encoding="utf-8"))
        if "target_cancel_payload" not in bd:
            return
        prof.target_cancel_payload = normalize_target_cancel_payload(str(bd["target_cancel_payload"]))
        if log_ok:
            log.info(
                "Migrated target_cancel_payload from %s → combat profile (use Auto combat tab / autocombat.json)",
                bpath.name,
            )
    except (OSError, ValueError, json.JSONDecodeError):
        pass


def load_profile(path: Path | None = None) -> CombatProfile:
    p = path or default_profile_path()
    if not p.is_file():
        prof = CombatProfile()
        _migrate_target_cancel_from_buffs_json(prof, log_ok=True)
        return prof
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        prof = CombatProfile.from_dict(data)
        if "target_cancel_payload" not in data:
            _migrate_target_cancel_from_buffs_json(prof, log_ok=True)
        return prof
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Failed to load combat profile %s: %s", p, exc)
        return CombatProfile()


def save_profile(profile: CombatProfile, path: Path | None = None) -> None:
    p = path or default_profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    log.info("Saved combat profile: %s (%d rules)", p, len(profile.rules))
