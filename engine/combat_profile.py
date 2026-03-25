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
    normalize_buff_skill_packet,
    normalize_magic_skill_payload,
    normalize_target_cancel_payload,
)
from engine.character_config import (
    character_buff_profile_path,
    legacy_buff_profile_path,
    legacy_combat_profile_path,
    resolve_combat_profile_read_path,
    resolve_combat_profile_write_path,
)

log = logging.getLogger(__name__)

# Auto-combat: max |npc.z - me.z| to ignore mobs on other floors / heights.
# Set to 0 in JSON to disable (horizontal range only). Tune per area (ramps, flying mobs).
DEFAULT_TARGET_Z_RANGE_MAX = 128.0

RuleType = Literal["skill", "item"]


def _int_id_list(raw: object) -> list[int]:
    out: list[int] = []
    if not raw:
        return out
    if isinstance(raw, (list, tuple)):
        for x in raw:
            try:
                v = int(x)
                if v > 0:
                    out.append(v)
            except (TypeError, ValueError):
                continue
    return out


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
    # Target (current mob) abnormal effect ids — spoil / debuff gating when server sends Abnormal for NPC.
    require_target_missing_abnormal_ids: list[int] = field(default_factory=list)
    require_target_has_abnormal_ids: list[int] = field(default_factory=list)
    # Run this rule on a dedicated pass before the first force-attack on a *new* target (retarget counts).
    fire_before_first_attack: bool = False

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
            require_target_missing_abnormal_ids=_int_id_list(
                d.get("require_target_missing_abnormal_ids")
            ),
            require_target_has_abnormal_ids=_int_id_list(
                d.get("require_target_has_abnormal_ids")
            ),
            fire_before_first_attack=bool(d.get("fire_before_first_attack", False)),
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
    # After post-kill regen: send up to this many RequestActionUse(0) toggles until server reports standing (or cap).
    recovery_stand_toggle_attempts: int = 3
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
    # RequestMagicSkillUse (0x39) body: dcb = classic 9B; ddd = many L2J/Teon 12B (match Buffs tab).
    magic_skill_payload: str = "ddd"
    # Combat skill C2S: 39 = RequestMagicSkillUse; 2f = Teon shortcut bar (same as force-attack packet).
    combat_skill_packet: str = "39"
    # Targeting (L2Net-style ideas; distances in world units — tune per shard)
    prefer_aggro_mobs: bool = True
    retain_current_target_max_dist: float = 650.0
    npc_blacklist_ids: list[int] = field(default_factory=list)
    npc_whitelist_ids: list[int] = field(default_factory=list)
    attack_only_whitelist_mobs: bool = False
    target_z_range_max: float = DEFAULT_TARGET_Z_RANGE_MAX
    # Default off: some shards / NpcInfo layouts mis-flag normal mobs as summoned → no targets.
    skip_summoned_npcs: bool = False
    never_attack_object_ids: list[int] = field(default_factory=list)
    party_protect_object_ids: list[int] = field(default_factory=list)
    combat_skill_min_interval_sec: float = 0.28
    # Reserved until pathing exists (no movement emitted when True).
    move_before_targeting: bool = False
    # Extra combat-rule evaluation during kill-loop (0 = only on engage + re-attack).
    combat_rules_tick_sec: float = 0.45
    # Post-kill: cast skill (e.g. Sweep) on corpse before RequestTargetCancel.
    post_kill_sweep_enabled: bool = False
    post_kill_sweep_skill_id: int = 0
    post_kill_sweep_delay_sec: float = 0.12
    # Leash mobs to combat anchor (set when auto-combat starts) — limits map drift.
    combat_anchor_leash_enabled: bool = False
    combat_anchor_leash_radius: float = 1800.0
    # After this many seconds with no mob in range, recenter anchor on character (0 = never).
    combat_anchor_reset_idle_sec: float = 0.0
    # Switch target mid-fight to a mob that recently hit you (see World._attackers_on_me).
    retarget_to_aggro_enabled: bool = True
    aggro_retarget_window_sec: float = 8.0
    # While idle (no mob in scan), sit between pulls — only if no active threat.
    combat_sit_while_idle_enabled: bool = False
    # When anchor leash enabled, also ignore ground loot farther than anchor radius from anchor.
    loot_respect_anchor_leash: bool = False

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
            "recovery_stand_toggle_attempts": self.recovery_stand_toggle_attempts,
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
            "combat_skill_packet": self.combat_skill_packet,
            "prefer_aggro_mobs": self.prefer_aggro_mobs,
            "retain_current_target_max_dist": self.retain_current_target_max_dist,
            "npc_blacklist_ids": list(self.npc_blacklist_ids),
            "npc_whitelist_ids": list(self.npc_whitelist_ids),
            "attack_only_whitelist_mobs": self.attack_only_whitelist_mobs,
            "target_z_range_max": self.target_z_range_max,
            "skip_summoned_npcs": self.skip_summoned_npcs,
            "never_attack_object_ids": list(self.never_attack_object_ids),
            "party_protect_object_ids": list(self.party_protect_object_ids),
            "combat_skill_min_interval_sec": self.combat_skill_min_interval_sec,
            "move_before_targeting": self.move_before_targeting,
            "combat_rules_tick_sec": self.combat_rules_tick_sec,
            "post_kill_sweep_enabled": self.post_kill_sweep_enabled,
            "post_kill_sweep_skill_id": self.post_kill_sweep_skill_id,
            "post_kill_sweep_delay_sec": self.post_kill_sweep_delay_sec,
            "combat_anchor_leash_enabled": self.combat_anchor_leash_enabled,
            "combat_anchor_leash_radius": self.combat_anchor_leash_radius,
            "combat_anchor_reset_idle_sec": self.combat_anchor_reset_idle_sec,
            "retarget_to_aggro_enabled": self.retarget_to_aggro_enabled,
            "aggro_retarget_window_sec": self.aggro_retarget_window_sec,
            "combat_sit_while_idle_enabled": self.combat_sit_while_idle_enabled,
            "loot_respect_anchor_leash": self.loot_respect_anchor_leash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CombatProfile":
        def _int_ids(key: str) -> list[int]:
            out: list[int] = []
            for x in (d.get(key) or []):
                try:
                    v = int(x)
                    if v != 0:
                        out.append(v)
                except (TypeError, ValueError):
                    continue
            return out

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
            recovery_change_wait_type_sit_raw=max(
                0, min(1, int(d.get("recovery_change_wait_type_sit_raw", 0)))
            ),
            recovery_stand_toggle_attempts=max(
                1, min(4, int(d.get("recovery_stand_toggle_attempts", 3)))
            ),
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
            magic_skill_payload=normalize_magic_skill_payload(str(d.get("magic_skill_payload", "ddd"))),
            combat_skill_packet=normalize_buff_skill_packet(str(d.get("combat_skill_packet", "39"))),
            prefer_aggro_mobs=bool(d.get("prefer_aggro_mobs", True)),
            retain_current_target_max_dist=float(d.get("retain_current_target_max_dist", 650)),
            npc_blacklist_ids=_int_ids("npc_blacklist_ids"),
            npc_whitelist_ids=_int_ids("npc_whitelist_ids"),
            attack_only_whitelist_mobs=bool(d.get("attack_only_whitelist_mobs", False)),
            target_z_range_max=float(
                d.get("target_z_range_max", DEFAULT_TARGET_Z_RANGE_MAX)
            ),
            skip_summoned_npcs=bool(d.get("skip_summoned_npcs", False)),
            never_attack_object_ids=_int_ids("never_attack_object_ids"),
            party_protect_object_ids=_int_ids("party_protect_object_ids"),
            combat_skill_min_interval_sec=float(d.get("combat_skill_min_interval_sec", 0.28)),
            move_before_targeting=bool(d.get("move_before_targeting", False)),
            combat_rules_tick_sec=float(d.get("combat_rules_tick_sec", 0.45)),
            post_kill_sweep_enabled=bool(d.get("post_kill_sweep_enabled", False)),
            post_kill_sweep_skill_id=int(d.get("post_kill_sweep_skill_id", 0)),
            post_kill_sweep_delay_sec=float(d.get("post_kill_sweep_delay_sec", 0.12)),
            combat_anchor_leash_enabled=bool(d.get("combat_anchor_leash_enabled", False)),
            combat_anchor_leash_radius=float(d.get("combat_anchor_leash_radius", 1800)),
            combat_anchor_reset_idle_sec=float(d.get("combat_anchor_reset_idle_sec", 0)),
            retarget_to_aggro_enabled=bool(d.get("retarget_to_aggro_enabled", True)),
            aggro_retarget_window_sec=float(d.get("aggro_retarget_window_sec", 8.0)),
            combat_sit_while_idle_enabled=bool(d.get("combat_sit_while_idle_enabled", False)),
            loot_respect_anchor_leash=bool(d.get("loot_respect_anchor_leash", False)),
        )

    def mp_recovery_enabled(self) -> bool:
        return self.recovery_sit_mp_below_pct > 0 and self.recovery_stand_mp_pct > 0


def default_profile_path(root: Path | None = None) -> Path:
    """Legacy global file (pre per-character layout)."""
    return legacy_combat_profile_path(root)


def _migrate_target_cancel_from_buffs_json(
    prof: "CombatProfile",
    *,
    log_ok: bool,
    character_name: str | None = None,
    root: Path | None = None,
) -> None:
    """Legacy: target_cancel_payload lived in buffs.json; now it belongs in autocombat.json."""
    r = root or Path(__file__).resolve().parents[1]
    candidates: list[Path] = []
    if character_name is not None:
        cb = character_buff_profile_path(character_name, r)
        if cb.is_file():
            candidates.append(cb)
    leg = legacy_buff_profile_path(r)
    if leg.is_file() and leg not in candidates:
        candidates.append(leg)
    for bpath in candidates:
        try:
            bd = json.loads(bpath.read_text(encoding="utf-8"))
            if "target_cancel_payload" not in bd:
                continue
            prof.target_cancel_payload = normalize_target_cancel_payload(
                str(bd["target_cancel_payload"])
            )
            if log_ok:
                log.info(
                    "Migrated target_cancel_payload from %s → combat profile",
                    bpath.as_posix(),
                )
            return
        except (OSError, ValueError, json.JSONDecodeError):
            continue


def load_profile(
    path: Path | None = None,
    *,
    character_name: str | None = None,
    root: Path | None = None,
) -> CombatProfile:
    r = root or Path(__file__).resolve().parents[1]
    migrate_as: str | None = character_name
    if path is not None:
        p = path
        migrate_as = None
    elif character_name is None:
        p = legacy_combat_profile_path(r)
    else:
        p, _ = resolve_combat_profile_read_path(character_name=character_name, root=r)
    if not p.is_file():
        prof = CombatProfile()
        _migrate_target_cancel_from_buffs_json(
            prof, log_ok=True, character_name=migrate_as, root=r
        )
        return prof
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        prof = CombatProfile.from_dict(data)
        if "target_cancel_payload" not in data:
            _migrate_target_cancel_from_buffs_json(
                prof, log_ok=True, character_name=migrate_as, root=r
            )
        return prof
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Failed to load combat profile %s: %s", p, exc)
        return CombatProfile()


def save_profile(
    profile: CombatProfile,
    path: Path | None = None,
    *,
    character_name: str | None = None,
    root: Path | None = None,
) -> None:
    r = root or Path(__file__).resolve().parents[1]
    if path is not None:
        p = path
    else:
        p = resolve_combat_profile_write_path(character_name=character_name, root=r)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    log.info("Saved combat profile: %s (%d rules)", p, len(profile.rules))
