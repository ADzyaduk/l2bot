"""
Buff maintenance profile: periodic skill casts with optional AbnormalStatus check.
Persisted as JSON per character under config/characters/<slug>/buffs.json
(fallback read: legacy config/buffs.json).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from engine.character_config import (
    legacy_buff_profile_path,
    resolve_buff_profile_read_path,
    resolve_buff_profile_write_path,
)

log = logging.getLogger(__name__)

BuffTargetMode = Literal["self", "current_target", "manual"]
SelfBuffPrecast = Literal["auto", "target_self", "none"]

_MAGIC_SKILL_PAYLOAD_VALID = frozenset({"dcb", "ddd", "dcc"})
_BUFF_SKILL_PACKET_VALID = frozenset({"39", "2f"})
_TARGET_CANCEL_PAYLOAD_VALID = frozenset({"h", "d"})
_SELF_BUFF_PRECAST_VALID = frozenset({"auto", "target_self", "none"})


def normalize_magic_skill_payload(value: str) -> str:
    """RequestMagicSkillUse (0x39) body layout for this server."""
    v = (value or "dcb").strip().lower()
    return v if v in _MAGIC_SKILL_PAYLOAD_VALID else "dcb"


def normalize_buff_skill_packet(value: str) -> str:
    """Buff loop C2S: 0x39 RequestMagicSkillUse vs 0x2F shortcut bar (Teon)."""
    v = (value or "39").strip().lower()
    if v in ("0x39", "0x2f"):
        v = v[2:]
    return v if v in _BUFF_SKILL_PACKET_VALID else "39"


def normalize_target_cancel_payload(value: str) -> str:
    """RequestTargetCancel (0x37) body: WORD(0) vs DWORD(0)."""
    v = (value or "h").strip().lower()
    return v if v in _TARGET_CANCEL_PAYLOAD_VALID else "h"


def normalize_self_buff_precast(value: str) -> SelfBuffPrecast:
    """What to send before 0x39 for target_mode=self (unless rule skips precast)."""
    v = (value or "auto").strip().lower()
    # 0x37 RequestTargetCancel before self-buff reliably disconnects on Teon / many L2J forks — removed from UI/JSON.
    if v == "cancel":
        log.warning(
            "buff profile: self_buff_before_cast 'cancel' (0x37) is ignored — use auto or target_self (0x04 self); "
            "saving the profile again will drop 'cancel' from the file",
        )
        return "target_self"
    if v in _SELF_BUFF_PRECAST_VALID:
        return v  # type: ignore[return-value]
    return "auto"


def _parse_skip_precast_for_self(d: dict[str, Any]) -> bool:
    """True = no 0x04-on-self step before self buff (ignores profile «Before self buff»)."""
    if bool(d.get("skip_precast_for_self", False)):
        return True
    if bool(d.get("skip_cancel_target_for_self", False)):
        return True
    if "clear_target_before_cast" in d and not bool(d.get("clear_target_before_cast")):
        return True
    return False


@dataclass
class BuffRule:
    enabled: bool = True
    skill_id: int = 0
    interval_sec: float = 1200.0
    # AbnormalStatusUpdate (server buff list) for this object:
    # - rebuff_if_missing True: effect id = check_buff_skill_id if set, else skill_id — cast when absent OR interval elapsed.
    # - rebuff_if_missing False: check_buff_skill_id only; if 0, pure timer (interval since last cast, ignores cancel).
    check_buff_skill_id: int = 0
    rebuff_if_missing: bool = True
    # If non-empty: buff is «present» if ANY of these ids appear in AbnormalStatus (server may not use cast skill id).
    abnormal_match_ids: list[int] = field(default_factory=list)
    target_mode: BuffTargetMode = "self"
    # For target_mode == "manual" — game objectId of ally (decimal; hex can be entered in UI as 0x...).
    target_object_id: int = 0
    # Minimum seconds between cast attempts for this rule (anti-spam).
    min_retry_sec: float = 2.0
    # If True, skip «Before self buff» precast (no 0x04 on self); risky if server still has wrong target.
    skip_precast_for_self: bool = False
    # Non-self: CS_Action with shift (ally select) instead of normal click (often starts attack).
    target_shift_click: bool = True
    # RequestMagicSkillUse ctrl flag (some servers/skills need force).
    skill_force_ctrl: bool = False
    # RequestMagicSkillUse shift byte (rare; try for some self/toggle skills).
    skill_force_shift: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["target_mode"] = self.target_mode
        d["abnormal_match_ids"] = list(self.abnormal_match_ids)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BuffRule":
        mode = d.get("target_mode", "self")
        if mode not in ("self", "current_target", "manual"):
            mode = "self"
        am_raw = d.get("abnormal_match_ids")
        abnormal_match_ids: list[int] = []
        if isinstance(am_raw, list):
            for x in am_raw:
                try:
                    v = int(x)
                    if v > 0:
                        abnormal_match_ids.append(v)
                except (TypeError, ValueError):
                    pass
        return cls(
            enabled=bool(d.get("enabled", True)),
            skill_id=int(d.get("skill_id", 0)),
            interval_sec=float(d.get("interval_sec", 1200)),
            check_buff_skill_id=int(d.get("check_buff_skill_id", 0)),
            rebuff_if_missing=bool(d.get("rebuff_if_missing", True)),
            abnormal_match_ids=abnormal_match_ids,
            target_mode=mode,  # type: ignore[arg-type]
            target_object_id=int(d.get("target_object_id", 0)),
            min_retry_sec=float(d.get("min_retry_sec", 2.0)),
            skip_precast_for_self=_parse_skip_precast_for_self(d),
            target_shift_click=bool(d.get("target_shift_click", True)),
            skill_force_ctrl=bool(d.get("skill_force_ctrl", False)),
            skill_force_shift=bool(d.get("skill_force_shift", False)),
        )


@dataclass
class BuffProfile:
    enabled: bool = True
    # How often the buff maintenance coroutine wakes up.
    maintenance_tick_sec: float = 1.5
    # Skip buff casts while auto-combat is on and in kill loop or targeting a live mob.
    pause_while_auto_combat_engaged: bool = True
    # Global cap: max buff C2S casts per rolling 60s window (0 = unlimited).
    max_buff_casts_per_minute: float = 0.0
    post_skill_delay: float = 0.4
    # Pause after 0x04 precast on self before 0x39 (only when foreign target was cleared).
    self_buff_precast_delay_sec: float = 0.35
    # RequestMagicSkillUse (0x39) for buff loop — many L2J forks use ddd (D+D+D); combat uses CombatProfile.
    magic_skill_payload: str = "ddd"
    # "39" = RequestMagicSkillUse; "2f" = same opcode as attack bar, skillId in first dword (Teon shortcut).
    buff_skill_packet: str = "39"
    # Before self buff 0x39: auto / target_self / none — never 0x37 (see normalize_self_buff_precast).
    self_buff_before_cast: str = "auto"
    rules: list[BuffRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "maintenance_tick_sec": self.maintenance_tick_sec,
            "pause_while_auto_combat_engaged": self.pause_while_auto_combat_engaged,
            "max_buff_casts_per_minute": self.max_buff_casts_per_minute,
            "post_skill_delay": self.post_skill_delay,
            "self_buff_precast_delay_sec": self.self_buff_precast_delay_sec,
            "magic_skill_payload": self.magic_skill_payload,
            "buff_skill_packet": self.buff_skill_packet,
            "self_buff_before_cast": self.self_buff_before_cast,
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BuffProfile":
        rules_raw = d.get("rules") or []
        rules = [BuffRule.from_dict(x) for x in rules_raw if isinstance(x, dict)]
        return cls(
            enabled=bool(d.get("enabled", True)),
            maintenance_tick_sec=float(d.get("maintenance_tick_sec", 1.5)),
            pause_while_auto_combat_engaged=bool(d.get("pause_while_auto_combat_engaged", True)),
            max_buff_casts_per_minute=float(d.get("max_buff_casts_per_minute", 0)),
            post_skill_delay=float(d.get("post_skill_delay", 0.4)),
            self_buff_precast_delay_sec=float(d.get("self_buff_precast_delay_sec", 0.35)),
            magic_skill_payload=normalize_magic_skill_payload(str(d.get("magic_skill_payload", "ddd"))),
            buff_skill_packet=normalize_buff_skill_packet(str(d.get("buff_skill_packet", "39"))),
            self_buff_before_cast=normalize_self_buff_precast(str(d.get("self_buff_before_cast", "auto"))),
            rules=rules,
        )


def default_buff_profile_path(root: Path | None = None) -> Path:
    """Legacy global file path."""
    return legacy_buff_profile_path(root)


def load_buff_profile(
    path: Path | None = None,
    *,
    character_name: str | None = None,
    root: Path | None = None,
) -> BuffProfile:
    r = root or Path(__file__).resolve().parents[1]
    if path is not None:
        p = path
    elif character_name is None:
        p = legacy_buff_profile_path(r)
    else:
        p, _ = resolve_buff_profile_read_path(character_name=character_name, root=r)
    if not p.is_file():
        return BuffProfile()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return BuffProfile.from_dict(data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Failed to load buff profile %s: %s", p, exc)
        return BuffProfile()


def save_buff_profile(
    profile: BuffProfile,
    path: Path | None = None,
    *,
    character_name: str | None = None,
    root: Path | None = None,
) -> None:
    r = root or Path(__file__).resolve().parents[1]
    if path is not None:
        p = path
    else:
        p = resolve_buff_profile_write_path(character_name=character_name, root=r)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    log.info("Saved buff profile: %s (%d rules)", p, len(profile.rules))
