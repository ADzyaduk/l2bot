"""Buff maintenance — periodic casts from config/buffs.json."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import game_reference as gre
from engine.buff_profile import (
    BuffProfile,
    BuffRule,
    load_buff_profile,
    normalize_buff_skill_packet,
    normalize_magic_skill_payload,
    normalize_self_buff_precast,
    save_buff_profile,
)
from ui import theme
from ui.scrollframe import ScrolledFrame


def _abn_id_display(r: BuffRule) -> str:
    """Effective AbnormalStatus skill id column, or timer."""
    if r.abnormal_match_ids:
        return ",".join(str(x) for x in r.abnormal_match_ids[:3]) + ("…" if len(r.abnormal_match_ids) > 3 else "")
    if r.rebuff_if_missing and r.skill_id > 0:
        eff = r.check_buff_skill_id if r.check_buff_skill_id > 0 else r.skill_id
        return str(eff)
    if r.check_buff_skill_id > 0:
        return str(r.check_buff_skill_id)
    return "timer"


def _parse_abnormal_match_ids(s: str) -> list[int]:
    out: list[int] = []
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = _parse_int_entry(part)
            if v > 0:
                out.append(v)
        except ValueError:
            pass
    return out


def _parse_int_entry(s: str) -> int:
    t = s.strip()
    if not t:
        return 0
    if t.lower().startswith("0x"):
        return int(t, 16)
    return int(t, 10)


class BuffsTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._profile = load_buff_profile()
        self._scroll = ScrolledFrame(parent)
        self.frame = self._scroll
        self._build()

    def _build(self) -> None:
        f = self._scroll.content
        ttk.Label(f, text="Buff maintenance", style=theme.S_TITLE).pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Label(
            f,
            text="Background buff loop. «Rebuff if missing» prefers AbnormalStatusUpdate (skill id or check id). "
            "Teon: toggles use S2C MagicSkillLaunched (0x48) for on/off level; SkillList is not enough (skill stays listed). "
            "SkillList is only used to detect «off» when a row is gone or level 0. "
            "Uncheck + check id 0 = timer-only. Short post-cast grace applies after your casts. "
            "Target self | current_target | manual objectId — bot sends Action on that id then skill (0x39). "
            "«Before self buff»: auto (0x04 self if needed) | target_self | none. "
            "After-kill target cancel (0x37) is on the Auto combat tab only.",
            style=theme.S_LABEL_MUTED,
            wraplength=780,
        ).pack(anchor="w", padx=14, pady=(0, 6))

        sched = ttk.LabelFrame(f, text="Buff loop scheduler", style=theme.S_LF)
        sched.pack(fill=tk.X, padx=10, pady=(0, 6))
        sr = ttk.Frame(sched, style=theme.S_FRAME)
        sr.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(sr, text="Tick interval (s)", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_tick = tk.StringVar(value=str(self._profile.maintenance_tick_sec))
        ttk.Entry(sr, textvariable=self._v_tick, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._v_pause_combat = tk.BooleanVar(value=self._profile.pause_while_auto_combat_engaged)
        ttk.Checkbutton(
            sr,
            text="Pause while auto-combat engaged (kill loop or hostile target)",
            variable=self._v_pause_combat,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(sr, text="Max buff casts / min (0=∞)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(16, 4))
        self._v_cap = tk.StringVar(value=str(self._profile.max_buff_casts_per_minute))
        ttk.Entry(sr, textvariable=self._v_cap, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT)

        top = ttk.Frame(f, style=theme.S_FRAME)
        top.pack(fill=tk.X, padx=12, pady=4)
        self._v_prof_en = tk.BooleanVar(value=self._profile.enabled)
        ttk.Checkbutton(
            top, text="Enable buff maintenance", variable=self._v_prof_en, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        ttk.Label(top, text="post-cast delay (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(16, 4))
        self._v_post_skill = tk.StringVar(value=str(self._profile.post_skill_delay))
        ttk.Entry(top, textvariable=self._v_post_skill, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT)
        ttk.Label(top, text="wait after 0x04 precast (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(14, 4))
        self._v_precast_delay = tk.StringVar(value=str(self._profile.self_buff_precast_delay_sec))
        ttk.Entry(top, textvariable=self._v_precast_delay, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT)

        top2 = ttk.Frame(f, style=theme.S_FRAME)
        top2.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(top2, text="C2S 0x39 skill body", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_magic_payload = tk.StringVar(value=self._profile.magic_skill_payload)
        ttk.Combobox(
            top2,
            textvariable=self._v_magic_payload,
            width=6,
            values=("dcb", "ddd", "dcc"),
            state="readonly",
            style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            top2,
            text="dcb=9B default · ddd=12B · dcc=6B",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT, padx=4)

        top2b = ttk.Frame(f, style=theme.S_FRAME)
        top2b.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(top2b, text="Buff C2S packet", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_buff_packet = tk.StringVar(value=normalize_buff_skill_packet(self._profile.buff_skill_packet))
        ttk.Combobox(
            top2b,
            textvariable=self._v_buff_packet,
            width=8,
            values=("39", "2f"),
            state="readonly",
            style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            top2b,
            text="39=MagicSkillUse · 2f=shortcut bar (Teon: plain=2f+skillId+ctrl+shift)",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT, padx=4)

        top3 = ttk.Frame(f, style=theme.S_FRAME)
        top3.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(top3, text="Before self buff 0x39", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_self_precast = tk.StringVar(
            value=normalize_self_buff_precast(self._profile.self_buff_before_cast)
        )
        ttk.Combobox(
            top3,
            textvariable=self._v_self_precast,
            width=14,
            values=("auto", "target_self", "none"),
            state="readonly",
            style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            top3,
            text="auto: 0x39 only if no target in bot; 0x04 self only if another target is selected",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT, padx=4)

        live = ttk.LabelFrame(f, text="Live SkillList (refresh ~2s)", style=theme.S_LF)
        live.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._live_skills = tk.Listbox(
            live, height=4, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        self._live_skills.pack(fill=tk.X, padx=6, pady=4)
        self._live_skills.bind("<Double-Button-1>", self._on_live_pick)

        cols = (
            "#", "On", "Skill", "Name", "Interval s", "Abn id", "Target", "ObjId", "Retry s", "Learned",
        )
        tree_fr = ttk.Frame(f, style=theme.S_FRAME)
        # Do not expand=True: otherwise Treeview eats all vertical space and pushes form + buttons off-screen.
        tree_fr.pack(fill=tk.X, padx=10, pady=(0, 4))
        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings", height=8, style=theme.S_TREE)
        wds = {
            "#": 28, "On": 36, "Skill": 52, "Name": 140, "Interval s": 72, "Abn id": 56,
            "Target": 80, "ObjId": 68, "Retry s": 52, "Learned": 52,
        }
        for c in cols:
            self._tree.heading(c, text=c)
            self._tree.column(c, width=wds.get(c, 64), anchor="center")
        sb = ttk.Scrollbar(tree_fr, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_form_from_selection())

        form = ttk.LabelFrame(f, text="Edit row (select in table or add new)", style=theme.S_LF)
        form.pack(fill=tk.X, padx=10, pady=(0, 6))
        r0 = ttk.Frame(form, style=theme.S_FRAME)
        r0.pack(fill=tk.X, padx=8, pady=4)
        self._v_en = tk.BooleanVar(value=True)
        ttk.Checkbutton(r0, text="Rule enabled", variable=self._v_en, style=theme.S_CHECK).pack(side=tk.LEFT)
        ttk.Label(r0, text="skill id", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 4))
        self._v_skill = tk.StringVar(value="0")
        ttk.Entry(r0, textvariable=self._v_skill, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT)
        ttk.Label(r0, text="interval (sec)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 4))
        self._v_interval = tk.StringVar(value="1200")
        ttk.Entry(r0, textvariable=self._v_interval, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT)
        ttk.Label(r0, text="check id", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 4))
        self._v_check = tk.StringVar(value="0")
        ttk.Entry(r0, textvariable=self._v_check, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT)
        self._v_rebuff_missing = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            r0,
            text="Rebuff if missing (AbnormalStatus)",
            variable=self._v_rebuff_missing,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(12, 0))

        r0d = ttk.Frame(form, style=theme.S_FRAME)
        r0d.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(
            r0d,
            text="Abnormal match ids (optional, comma) — if empty, uses check/skill id",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT)
        self._v_abnormal_match = tk.StringVar(value="")
        ttk.Entry(r0d, textvariable=self._v_abnormal_match, width=36, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=6)

        r1 = ttk.Frame(form, style=theme.S_FRAME)
        r1.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(r1, text="Target", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_target = tk.StringVar(value="self")
        ttk.Combobox(
            r1, textvariable=self._v_target, width=14,
            values=("self", "current_target", "manual"), state="readonly", style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(r1, text="manual objectId", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 4))
        self._v_oid = tk.StringVar(value="0")
        ttk.Entry(r1, textvariable=self._v_oid, width=14, style=theme.S_ENTRY).pack(side=tk.LEFT)
        ttk.Label(r1, text="min retry (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 4))
        self._v_retry = tk.StringVar(value="2")
        ttk.Entry(r1, textvariable=self._v_retry, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT)
        self._id_hint = tk.StringVar(value="")
        ttk.Label(r1, textvariable=self._id_hint, style=theme.S_LABEL_MUTED).pack(side=tk.LEFT, padx=(12, 0))

        r1b = ttk.Frame(form, style=theme.S_FRAME)
        r1b.pack(fill=tk.X, padx=8, pady=2)
        self._v_skip_precast = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            r1b,
            text="Skip precast before self buff (unsafe if wrong target on server)",
            variable=self._v_skip_precast,
            style=theme.S_CHECK,
        ).pack(anchor="w", side=tk.LEFT)
        r1c = ttk.Frame(form, style=theme.S_FRAME)
        r1c.pack(fill=tk.X, padx=8, pady=2)
        self._v_shift = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            r1c,
            text="Ally: shift-click to target",
            variable=self._v_shift,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        self._v_force_ctrl = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            r1c,
            text="Skill: force ctrl",
            variable=self._v_force_ctrl,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(16, 0))
        self._v_force_shift = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            r1c,
            text="Skill: force shift",
            variable=self._v_force_shift,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(16, 0))

        r2 = ttk.LabelFrame(f, text="Rules", style=theme.S_LF)
        r2.pack(fill=tk.X, padx=10, pady=(0, 10))
        r2b = ttk.Frame(r2, style=theme.S_FRAME)
        r2b.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(r2b, text="Add rule", command=self._add_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r2b, text="Update selected", command=self._update_selected, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=3)
        ttk.Button(r2b, text="Remove", command=self._remove_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r2b, text="Move up", command=lambda: self._move(-1), style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r2b, text="Move down", command=lambda: self._move(1), style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r2b, text="Save to file", command=self._save_file, style=theme.S_BTN).pack(side=tk.LEFT, padx=12)
        ttk.Button(r2b, text="Reload file", command=self._reload_file, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)

        self._v_skill.trace_add("write", lambda *_: self._hint_skill())
        self._refresh_tree()
        self._push_profile()
        self._tick_live()

    def _hint_skill(self) -> None:
        try:
            n = _parse_int_entry(self._v_skill.get())
        except ValueError:
            self._id_hint.set("")
            return
        self._id_hint.set(gre.format_skill_choice(n))

    def _tick_live(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        self._live_skills.delete(0, tk.END)
        if not be:
            self._live_skills.insert(tk.END, "(no session — connect client)")
        elif not be.world.my_skills:
            self._live_skills.insert(tk.END, "(empty — enter world / SkillList)")
        else:
            for sid in sorted(be.world.my_skills.keys()):
                lv = be.world.my_skills[sid]
                nm = gre.resolve_skill_name(sid) or "?"
                self._live_skills.insert(tk.END, f"{sid}  L{lv}  —  {nm}")
        self._refresh_learned_column()
        self._scroll.after(2000, self._tick_live)

    def _on_live_pick(self, _evt=None) -> None:
        sel = self._live_skills.curselection()
        if not sel:
            return
        line = self._live_skills.get(sel[0])
        sid = int(line.split()[0].strip())
        self._v_skill.set(str(sid))
        self._hint_skill()

    def _learned_label(self, r: BuffRule) -> str:
        be = getattr(self.bot, "bot_engine", None)
        if not be or not be.world.my_skills:
            return "?"
        return "yes" if r.skill_id in be.world.my_skills else "no"

    def _row_values(self, i: int, r: BuffRule) -> tuple:
        nm = gre.resolve_skill_name(r.skill_id) or "—"
        return (
            str(i + 1),
            "yes" if r.enabled else "no",
            str(r.skill_id),
            nm[:28],
            f"{r.interval_sec:g}",
            _abn_id_display(r),
            r.target_mode,
            hex(r.target_object_id) if r.target_object_id else "—",
            f"{r.min_retry_sec:g}",
            self._learned_label(r),
        )

    def _refresh_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for i, r in enumerate(self._profile.rules):
            self._tree.insert("", tk.END, iid=str(i), values=self._row_values(i, r))

    def _refresh_learned_column(self) -> None:
        for i, r in enumerate(self._profile.rules):
            iid = str(i)
            if self._tree.exists(iid):
                self._tree.set(iid, "Learned", self._learned_label(r))
                self._tree.set(iid, "Abn id", _abn_id_display(r))

    def _sync_form_from_selection(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        r = self._profile.rules[int(sel[0])]
        self._v_en.set(r.enabled)
        self._v_skill.set(str(r.skill_id))
        self._v_interval.set(str(r.interval_sec))
        self._v_check.set(str(r.check_buff_skill_id))
        self._v_rebuff_missing.set(getattr(r, "rebuff_if_missing", True))
        am = getattr(r, "abnormal_match_ids", None) or []
        self._v_abnormal_match.set(", ".join(str(x) for x in am))
        self._v_target.set(r.target_mode)
        self._v_oid.set(hex(r.target_object_id) if r.target_object_id else "0")
        self._v_retry.set(str(r.min_retry_sec))
        self._v_skip_precast.set(r.skip_precast_for_self)
        self._v_shift.set(r.target_shift_click)
        self._v_force_ctrl.set(r.skill_force_ctrl)
        self._v_force_shift.set(getattr(r, "skill_force_shift", False))
        self._hint_skill()

    def _parse_rule_from_form(self) -> BuffRule | None:
        try:
            sid = _parse_int_entry(self._v_skill.get())
            interval = float(self._v_interval.get().strip() or 1200)
            check = _parse_int_entry(self._v_check.get())
            oid = _parse_int_entry(self._v_oid.get())
            retry = float(self._v_retry.get().strip() or 2)
        except ValueError:
            messagebox.showerror("Buffs", "Invalid number in skill id, interval, check id, objectId, or retry.")
            return None
        tm = self._v_target.get()
        if tm not in ("self", "current_target", "manual"):
            tm = "self"
        if sid <= 0:
            messagebox.showerror("Buffs", "skill id must be > 0.")
            return None
        return BuffRule(
            enabled=self._v_en.get(),
            skill_id=sid,
            interval_sec=max(1.0, interval),
            check_buff_skill_id=max(0, check),
            rebuff_if_missing=self._v_rebuff_missing.get(),
            abnormal_match_ids=_parse_abnormal_match_ids(self._v_abnormal_match.get()),
            target_mode=tm,  # type: ignore[arg-type]
            target_object_id=max(0, oid),
            min_retry_sec=max(0.0, retry),
            skip_precast_for_self=self._v_skip_precast.get(),
            target_shift_click=self._v_shift.get(),
            skill_force_ctrl=self._v_force_ctrl.get(),
            skill_force_shift=self._v_force_shift.get(),
        )

    def _apply_globals(self) -> bool:
        try:
            self._profile.enabled = self._v_prof_en.get()
            self._profile.maintenance_tick_sec = float(self._v_tick.get().strip() or 1.5)
            self._profile.pause_while_auto_combat_engaged = self._v_pause_combat.get()
            self._profile.max_buff_casts_per_minute = float(self._v_cap.get().strip() or 0)
            self._profile.post_skill_delay = float(self._v_post_skill.get().strip() or 0.4)
            self._profile.self_buff_precast_delay_sec = float(
                self._v_precast_delay.get().strip() or 0.35
            )
            self._profile.magic_skill_payload = normalize_magic_skill_payload(self._v_magic_payload.get())
            self._profile.buff_skill_packet = normalize_buff_skill_packet(self._v_buff_packet.get())
            self._profile.self_buff_before_cast = normalize_self_buff_precast(self._v_self_precast.get())
            self._v_magic_payload.set(self._profile.magic_skill_payload)
            self._v_buff_packet.set(self._profile.buff_skill_packet)
            self._v_self_precast.set(self._profile.self_buff_before_cast)
        except ValueError:
            messagebox.showerror("Buffs", "Invalid scheduler, post-cast, or precast delay.")
            return False
        return True

    def _add_rule(self) -> None:
        if not self._apply_globals():
            return
        r = self._parse_rule_from_form()
        if r is None:
            return
        self._profile.rules.append(r)
        self._push_profile()

    def _update_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Buffs", "Select a rule row first.")
            return
        if not self._apply_globals():
            return
        r = self._parse_rule_from_form()
        if r is None:
            return
        self._profile.rules[int(sel[0])] = r
        self._push_profile()

    def _remove_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        del self._profile.rules[int(sel[0])]
        self._push_profile()

    def _move(self, delta: int) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        j = idx + delta
        if j < 0 or j >= len(self._profile.rules):
            return
        self._profile.rules[idx], self._profile.rules[j] = (
            self._profile.rules[j], self._profile.rules[idx])
        self._push_profile()
        self._tree.selection_set(str(j))

    def _save_file(self) -> None:
        if not self._apply_globals():
            return
        save_buff_profile(self._profile)
        messagebox.showinfo("Buffs", f"Saved {len(self._profile.rules)} rules to config/buffs.json.")

    def _reload_file(self) -> None:
        cb = getattr(self.bot, "reload_buff_profile_from_disk", None)
        if cb:
            self._profile = cb()
        else:
            self._profile = load_buff_profile()
        self._v_prof_en.set(self._profile.enabled)
        self._v_tick.set(str(self._profile.maintenance_tick_sec))
        self._v_pause_combat.set(self._profile.pause_while_auto_combat_engaged)
        self._v_cap.set(str(self._profile.max_buff_casts_per_minute))
        self._v_post_skill.set(str(self._profile.post_skill_delay))
        self._v_precast_delay.set(str(self._profile.self_buff_precast_delay_sec))
        self._v_magic_payload.set(self._profile.magic_skill_payload)
        self._v_buff_packet.set(normalize_buff_skill_packet(self._profile.buff_skill_packet))
        self._v_self_precast.set(normalize_self_buff_precast(self._profile.self_buff_before_cast))
        self._push_profile()

    def _push_profile(self) -> None:
        if not self._apply_globals():
            return
        self._refresh_tree()
        cb = getattr(self.bot, "apply_buff_profile", None)
        if cb:
            cb(self._profile)
