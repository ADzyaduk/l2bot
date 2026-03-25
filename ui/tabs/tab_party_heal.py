"""Party heal / mana / buff — rule editor tab."""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from core import game_reference as gre
from engine.character_config import resolve_party_profile_write_path
from engine.party_profile import (
    PartyHealRule,
    PartyProfile,
    load_party_profile,
    save_party_profile,
)
from ui import theme
from ui.scrollframe import ScrolledFrame

_log = logging.getLogger(__name__)

_KIND_OPTIONS = ("heal", "mana", "buff")


def _parse_int_entry(s: str) -> int:
    t = s.strip()
    if not t:
        return 0
    if t.lower().startswith("0x"):
        return int(t, 16)
    return int(t, 10)


def _parse_skill_combo_line(line: str) -> int | None:
    """Extract skill ID from combo line like '1217 — Heal' or just '1217'."""
    line = (line or "").strip()
    if not line:
        return None
    head = line.split("—", 1)[0].strip() if "—" in line else line.split(None, 1)[0].strip()
    try:
        return int(head, 10)
    except ValueError:
        try:
            return int(head, 16)
        except ValueError:
            return None


def _skill_display(skill_id: int, combo_values: list[str]) -> str:
    """Find matching combo entry for skill_id, or build a fallback label."""
    sid_str = str(skill_id)
    for v in combo_values:
        if v.split("—", 1)[0].strip() == sid_str:
            return v
    name = gre.resolve_skill_name(skill_id) if skill_id > 0 else ""
    if name:
        return f"{skill_id} — {name}"
    return str(skill_id) if skill_id > 0 else ""


class PartyHealTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._profile = self._load_profile()
        self._scroll = ScrolledFrame(parent)
        self.frame = self._scroll
        self._rule_widgets: list[dict] = []
        self._skill_combos: list[ttk.Combobox] = []
        self._build()

    def _character_name(self) -> str | None:
        be = getattr(self.bot, "bot_engine", None)
        if not be:
            return None
        return be.world.me.name or ""

    def _load_profile(self) -> PartyProfile:
        cn = self._character_name()
        if cn is None:
            return load_party_profile(None)
        return load_party_profile(character_name=cn)

    def refresh_profile_from_disk(self) -> None:
        self._profile = self._load_profile()
        self._rebuild_rules()
        self._refresh_skill_combos()

    # ------------------------------------------------------------------ #
    # Skill dropdown helpers
    # ------------------------------------------------------------------ #

    def _skill_combo_values(self) -> list[str]:
        """Build list of learned skills as 'ID — Name' for dropdown."""
        be = getattr(self.bot, "bot_engine", None)
        if not be or not be.world.my_skills:
            return []
        out: list[str] = []
        for sid in sorted(be.world.my_skills.keys()):
            nm = gre.resolve_skill_name(sid) or "?"
            out.append(f"{sid} — {nm}")
        return out

    def _refresh_skill_combos(self) -> None:
        """Update all skill Combobox dropdowns with current learned skills."""
        vals = self._skill_combo_values()
        for cb in self._skill_combos:
            try:
                cb.configure(values=vals)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------ #
    # Build UI
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        f = self._scroll.content

        ttk.Label(f, text="Party heal / mana / buffs", style=theme.S_TITLE).pack(
            anchor="w", padx=14, pady=(14, 8)
        )

        # Global settings row
        top = ttk.Frame(f, style=theme.S_FRAME)
        top.pack(fill=tk.X, padx=14, pady=(0, 6))

        self._v_enabled = tk.BooleanVar(value=self._profile.enabled)
        ttk.Checkbutton(
            top, text="Enable party support", variable=self._v_enabled, style=theme.S_CHECK
        ).pack(side=tk.LEFT)

        self._v_self_first = tk.BooleanVar(value=self._profile.heal_self_first)
        ttk.Checkbutton(
            top, text="Self-heal priority", variable=self._v_self_first, style=theme.S_CHECK
        ).pack(side=tk.LEFT, padx=(16, 0))

        # Self HP critical threshold
        row2 = ttk.Frame(f, style=theme.S_FRAME)
        row2.pack(fill=tk.X, padx=14, pady=(0, 6))

        ttk.Label(row2, text="Self HP critical %:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_self_crit = tk.StringVar(value=str(self._profile.self_hp_critical_pct))
        ttk.Entry(row2, textvariable=self._v_self_crit, width=6, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Label(row2, text="Poll interval (s):", style=theme.S_LABEL).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        self._v_poll = tk.StringVar(value=str(self._profile.poll_interval_sec))
        ttk.Entry(row2, textvariable=self._v_poll, width=6, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Label(row2, text="Target switch delay (s):", style=theme.S_LABEL).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        self._v_switch_delay = tk.StringVar(value=str(self._profile.target_switch_delay_sec))
        ttk.Entry(row2, textvariable=self._v_switch_delay, width=6, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4
        )

        # Pause while combat
        self._v_pause_combat = tk.BooleanVar(value=self._profile.pause_while_combat_engaged)
        ttk.Checkbutton(
            row2, text="Pause during combat", variable=self._v_pause_combat, style=theme.S_CHECK
        ).pack(side=tk.LEFT, padx=(16, 0))

        # Rules list
        self._rules_frame = ttk.Frame(f, style=theme.S_FRAME)
        self._rules_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 4))

        self._rebuild_rules()

        # Buttons
        btn_row = ttk.Frame(f, style=theme.S_FRAME)
        btn_row.pack(fill=tk.X, padx=14, pady=(4, 8))
        ttk.Button(
            btn_row, text="Add rule", command=self._add_rule, style=theme.S_BTN
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btn_row, text="Save to file", command=self._save, style=theme.S_BTN_PRIMARY
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btn_row, text="Reload from file", command=self._reload, style=theme.S_BTN
        ).pack(side=tk.LEFT, padx=2)

    # ------------------------------------------------------------------ #
    # Rules list
    # ------------------------------------------------------------------ #

    def _rebuild_rules(self) -> None:
        for w in self._rules_frame.winfo_children():
            w.destroy()
        self._rule_widgets.clear()
        self._skill_combos.clear()

        # Header
        hdr = ttk.Frame(self._rules_frame, style=theme.S_FRAME)
        hdr.pack(fill=tk.X, pady=(4, 2))
        for col, (text, w) in enumerate((
            ("On", 3), ("Kind", 6), ("Skill", 30), ("HP< %", 6),
            ("MP< %", 6), ("CD (s)", 6), ("Prio", 4),
            ("Rebuff", 5), ("Check ID", 8), ("Interval (s)", 8), ("", 4),
        )):
            ttk.Label(hdr, text=text, width=w, style=theme.S_LABEL).pack(side=tk.LEFT, padx=1)

        combo_vals = self._skill_combo_values()
        for idx, rule in enumerate(self._profile.rules):
            self._build_rule_row(idx, rule, combo_vals)

    def _build_rule_row(self, idx: int, rule: PartyHealRule, combo_vals: list[str] | None = None) -> None:
        if combo_vals is None:
            combo_vals = self._skill_combo_values()

        row = ttk.Frame(self._rules_frame, style=theme.S_FRAME)
        row.pack(fill=tk.X, pady=1)

        v_en = tk.BooleanVar(value=rule.enabled)
        ttk.Checkbutton(row, variable=v_en, width=3, style=theme.S_CHECK).pack(side=tk.LEFT, padx=1)

        v_kind = tk.StringVar(value=rule.kind)
        kind_cb = ttk.Combobox(row, textvariable=v_kind, values=_KIND_OPTIONS, width=5, state="readonly")
        kind_cb.pack(side=tk.LEFT, padx=1)

        # Skill dropdown — same as Buffs tab
        v_skill = tk.StringVar(value=_skill_display(rule.skill_id, combo_vals))
        skill_cb = ttk.Combobox(row, textvariable=v_skill, values=combo_vals, width=28, style=theme.S_ENTRY)
        skill_cb.pack(side=tk.LEFT, padx=1)
        self._skill_combos.append(skill_cb)

        v_hp = tk.StringVar(value=str(rule.hp_below_pct))
        ttk.Entry(row, textvariable=v_hp, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=1)

        v_mp = tk.StringVar(value=str(rule.mp_below_pct))
        ttk.Entry(row, textvariable=v_mp, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=1)

        v_cd = tk.StringVar(value=str(rule.cooldown_sec))
        ttk.Entry(row, textvariable=v_cd, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=1)

        v_prio = tk.StringVar(value=str(rule.priority))
        ttk.Entry(row, textvariable=v_prio, width=4, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=1)

        v_rebuff = tk.BooleanVar(value=rule.rebuff_if_missing)
        ttk.Checkbutton(row, variable=v_rebuff, width=5, style=theme.S_CHECK).pack(side=tk.LEFT, padx=1)

        v_check = tk.StringVar(value=str(rule.check_buff_skill_id) if rule.check_buff_skill_id else "")
        ttk.Entry(row, textvariable=v_check, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=1)

        v_interval = tk.StringVar(value=str(rule.interval_sec))
        ttk.Entry(row, textvariable=v_interval, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=1)

        ttk.Button(
            row, text="X", width=3, command=lambda i=idx: self._delete_rule(i), style=theme.S_BTN
        ).pack(side=tk.LEFT, padx=1)

        self._rule_widgets.append({
            "v_en": v_en, "v_kind": v_kind, "v_skill": v_skill,
            "v_hp": v_hp, "v_mp": v_mp, "v_cd": v_cd, "v_prio": v_prio,
            "v_rebuff": v_rebuff, "v_check": v_check, "v_interval": v_interval,
        })

    def _add_rule(self) -> None:
        combo_vals = self._skill_combo_values()
        rule = PartyHealRule()
        # Pre-select first available skill if any
        if combo_vals:
            sid = _parse_skill_combo_line(combo_vals[0])
            if sid:
                rule = PartyHealRule(skill_id=sid)
        self._profile.rules.append(rule)
        self._build_rule_row(len(self._profile.rules) - 1, rule, combo_vals)

    def _delete_rule(self, idx: int) -> None:
        if 0 <= idx < len(self._profile.rules):
            self._profile.rules.pop(idx)
            self._rebuild_rules()

    # ------------------------------------------------------------------ #
    # Save / Load
    # ------------------------------------------------------------------ #

    def _collect_profile(self) -> PartyProfile:
        rules: list[PartyHealRule] = []
        for w in self._rule_widgets:
            skill_text = w["v_skill"].get()
            sid = _parse_skill_combo_line(skill_text)
            skill_id = sid if sid is not None else 0

            rules.append(PartyHealRule(
                enabled=w["v_en"].get(),
                kind=w["v_kind"].get() or "heal",  # type: ignore[arg-type]
                skill_id=skill_id,
                hp_below_pct=float(w["v_hp"].get() or "70"),
                mp_below_pct=float(w["v_mp"].get() or "50"),
                cooldown_sec=float(w["v_cd"].get() or "1"),
                priority=int(w["v_prio"].get() or "0"),
                rebuff_if_missing=w["v_rebuff"].get(),
                check_buff_skill_id=_parse_int_entry(w["v_check"].get() or "0"),
                interval_sec=float(w["v_interval"].get() or "1200"),
            ))

        return PartyProfile(
            enabled=self._v_enabled.get(),
            rules=rules,
            heal_self_first=self._v_self_first.get(),
            self_hp_critical_pct=float(self._v_self_crit.get() or "30"),
            poll_interval_sec=float(self._v_poll.get() or "0.5"),
            target_switch_delay_sec=float(self._v_switch_delay.get() or "0.3"),
            magic_skill_payload=self._profile.magic_skill_payload,
            party_skill_packet=self._profile.party_skill_packet,
            pause_while_combat_engaged=self._v_pause_combat.get(),
        )

    def _save(self) -> None:
        try:
            prof = self._collect_profile()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Error", f"Invalid value: {exc}")
            return
        cn = self._character_name()
        save_party_profile(prof, character_name=cn)
        self._profile = prof
        # Apply to running bot engine
        be = getattr(self.bot, "bot_engine", None)
        if be:
            be.set_party_profile(prof)
        _log.info("[PartyHealTab] Profile saved (%d rules)", len(prof.rules))

    def _reload(self) -> None:
        self._profile = self._load_profile()
        self._rebuild_rules()
        # Refresh vars
        self._v_enabled.set(self._profile.enabled)
        self._v_self_first.set(self._profile.heal_self_first)
        self._v_self_crit.set(str(self._profile.self_hp_critical_pct))
        self._v_poll.set(str(self._profile.poll_interval_sec))
        self._v_switch_delay.set(str(self._profile.target_switch_delay_sec))
        self._v_pause_combat.set(self._profile.pause_while_combat_engaged)
        _log.info("[PartyHealTab] Profile reloaded from disk")
