"""Buff maintenance — simple Self / Party tabs + optional Advanced."""
from __future__ import annotations

import logging
from dataclasses import replace
import tkinter as tk
from tkinter import messagebox, ttk

from core import game_reference as gre
from engine.character_config import resolve_buff_profile_write_path
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
from ui.profile_simple import (
    buff_filtered_indices,
    buff_rule_is_party_manual,
    buff_rule_is_self,
    interval_display_minutes,
    interval_sec_from_minutes,
)
from ui.scrollframe import ScrolledFrame

_log = logging.getLogger(__name__)


def _abn_id_display(r: BuffRule) -> str:
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


def _parse_skill_combo_line(line: str) -> int | None:
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


class BuffsTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._profile = self._load_profile_for_ui()
        self._scroll = ScrolledFrame(parent)
        self.frame = self._scroll
        self._party_display_to_oid: dict[str, int] = {}
        self._build()

    def _character_name_for_config(self) -> str | None:
        be = getattr(self.bot, "bot_engine", None)
        if not be:
            return None
        return be.world.me.name or ""

    def _load_profile_for_ui(self) -> BuffProfile:
        cn = self._character_name_for_config()
        if cn is None:
            return load_buff_profile(None)
        return load_buff_profile(character_name=cn)

    def refresh_profile_from_disk(self) -> None:
        self._reload_file()

    def _build(self) -> None:
        f = self._scroll.content
        ttk.Label(f, text="Buff maintenance", style=theme.S_TITLE).pack(anchor="w", padx=14, pady=(14, 8))

        top = ttk.Frame(f, style=theme.S_FRAME)
        top.pack(fill=tk.X, padx=14, pady=(0, 6))
        self._v_prof_en = tk.BooleanVar(value=self._profile.enabled)
        ttk.Checkbutton(
            top, text="Enable buff maintenance", variable=self._v_prof_en, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        self._path_hint = ttk.Label(top, text="", style=theme.S_LABEL_MUTED)
        self._path_hint.pack(side=tk.LEFT, padx=(16, 0))
        self._update_path_hint()

        nb = ttk.Notebook(f, style=theme.S_NOTEBOOK)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        self_frm = ttk.Frame(nb, style=theme.S_FRAME)
        party_frm = ttk.Frame(nb, style=theme.S_FRAME)
        nb.add(self_frm, text="Self")
        nb.add(party_frm, text="Party")
        self._build_simple_self(self_frm)
        self._build_simple_party(party_frm)

        act = ttk.Frame(f, style=theme.S_FRAME)
        act.pack(fill=tk.X, padx=14, pady=(4, 6))
        self._btn_buff_save = ttk.Button(act, text="Save to file", command=self._save_file, style=theme.S_BTN_PRIMARY)
        self._btn_buff_save.pack(side=tk.LEFT, padx=2)
        ttk.Button(act, text="Reload from file", command=self._reload_file, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)

        self._adv_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f, text="Show advanced", variable=self._adv_show, command=self._toggle_advanced, style=theme.S_CHECK,
        ).pack(anchor="w", padx=14, pady=(0, 4))
        self._adv_frame = ttk.Frame(f, style=theme.S_FRAME)
        self._build_advanced(self._adv_frame)

        self._v_skill.trace_add("write", lambda *_: self._hint_skill())
        self._refresh_all_trees()
        self._push_profile()
        self._tick_live()

    def _toggle_advanced(self) -> None:
        if self._adv_show.get():
            self._adv_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 8))
        else:
            self._adv_frame.pack_forget()

    def _build_simple_self(self, parent: tk.Widget) -> None:
        lf = ttk.LabelFrame(parent, text="Buffs on yourself", style=theme.S_LF)
        lf.pack(fill=tk.BOTH, expand=True, padx=4, pady=8)
        ttk.Label(
            lf,
            text="Empty list = no buff rules on self. Order is rule order in the profile.",
            style=theme.S_LABEL_MUTED,
        ).pack(anchor="w", padx=10, pady=(8, 4))

        cols = ("#", "On", "Skill", "Name", "min", "Re-cast", "Learned")
        tf = ttk.Frame(lf, style=theme.S_FRAME)
        tf.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._tree_self = ttk.Treeview(tf, columns=cols, show="headings", height=7, style=theme.S_TREE)
        wds = {"#": 32, "On": 36, "Skill": 52, "Name": 200, "min": 44, "Re-cast": 56, "Learned": 52}
        for c in cols:
            self._tree_self.heading(c, text=c)
            self._tree_self.column(c, width=wds[c], anchor="center")
        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._tree_self.yview)
        self._tree_self.configure(yscrollcommand=sb.set)
        self._tree_self.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree_self.bind("<<TreeviewSelect>>", lambda _e: self._sync_simple_form(False))

        ed = ttk.Frame(lf, style=theme.S_FRAME)
        ed.pack(fill=tk.X, padx=10, pady=6)
        self._s_skill_var = tk.StringVar()
        self._s_skill_combo = ttk.Combobox(ed, textvariable=self._s_skill_var, width=42, state="readonly", style=theme.S_ENTRY)
        self._s_skill_combo.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(ed, text="Every (min)", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._s_minutes = tk.StringVar(value="20")
        ttk.Entry(ed, textvariable=self._s_minutes, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._s_rebuff = tk.BooleanVar(value=True)
        ttk.Checkbutton(ed, text="Re-cast if missing", variable=self._s_rebuff, style=theme.S_CHECK).pack(
            side=tk.LEFT, padx=(10, 0))
        self._s_en = tk.BooleanVar(value=True)
        ttk.Checkbutton(ed, text="Enabled", variable=self._s_en, style=theme.S_CHECK).pack(side=tk.LEFT, padx=(8, 0))

        bt = ttk.Frame(lf, style=theme.S_FRAME)
        bt.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(bt, text="Add", command=lambda: self._add_simple(False), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Update", command=lambda: self._update_simple(False), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Remove", command=lambda: self._remove_simple(False), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Up", command=lambda: self._move_simple(False, -1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Down", command=lambda: self._move_simple(False, 1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)

    def _build_simple_party(self, parent: tk.Widget) -> None:
        lf = ttk.LabelFrame(parent, text="Buffs on party members", style=theme.S_LF)
        lf.pack(fill=tk.BOTH, expand=True, padx=4, pady=8)
        ttk.Label(
            lf,
            text="Select a party member in-game. If the list is empty, join a party.",
            style=theme.S_LABEL_MUTED,
        ).pack(anchor="w", padx=10, pady=(8, 4))

        cols = ("#", "On", "Member", "Skill", "Name", "min", "Re-cast", "Learned")
        tf = ttk.Frame(lf, style=theme.S_FRAME)
        tf.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._tree_party = ttk.Treeview(tf, columns=cols, show="headings", height=7, style=theme.S_TREE)
        wds = {"#": 28, "On": 32, "Member": 100, "Skill": 48, "Name": 160, "min": 40, "Re-cast": 52, "Learned": 48}
        for c in cols:
            self._tree_party.heading(c, text=c)
            self._tree_party.column(c, width=wds[c], anchor="center")
        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._tree_party.yview)
        self._tree_party.configure(yscrollcommand=sb.set)
        self._tree_party.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree_party.bind("<<TreeviewSelect>>", lambda _e: self._sync_simple_form(True))

        ed = ttk.Frame(lf, style=theme.S_FRAME)
        ed.pack(fill=tk.X, padx=10, pady=6)
        ttk.Label(ed, text="Member", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._p_member_var = tk.StringVar()
        self._p_member_combo = ttk.Combobox(ed, textvariable=self._p_member_var, width=22, state="readonly", style=theme.S_ENTRY)
        self._p_member_combo.pack(side=tk.LEFT, padx=4)
        self._p_skill_var = tk.StringVar()
        self._p_skill_combo = ttk.Combobox(ed, textvariable=self._p_skill_var, width=36, state="readonly", style=theme.S_ENTRY)
        self._p_skill_combo.pack(side=tk.LEFT, padx=(8, 0))
        row2 = ttk.Frame(lf, style=theme.S_FRAME)
        row2.pack(fill=tk.X, padx=10, pady=4)
        ttk.Label(row2, text="Every (min)", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._p_minutes = tk.StringVar(value="20")
        ttk.Entry(row2, textvariable=self._p_minutes, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._p_rebuff = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="Re-cast if missing", variable=self._p_rebuff, style=theme.S_CHECK).pack(
            side=tk.LEFT, padx=(10, 0))
        self._p_en = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="Enabled", variable=self._p_en, style=theme.S_CHECK).pack(side=tk.LEFT, padx=(8, 0))

        bt = ttk.Frame(lf, style=theme.S_FRAME)
        bt.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(bt, text="Add", command=lambda: self._add_simple(True), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Update", command=lambda: self._update_simple(True), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Remove", command=lambda: self._remove_simple(True), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Up", command=lambda: self._move_simple(True, -1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(bt, text="Down", command=lambda: self._move_simple(True, 1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)

    def _build_advanced(self, f: tk.Widget) -> None:
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
            text="Pause while auto-combat engaged",
            variable=self._v_pause_combat,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(sr, text="Max buff casts / min (0=∞)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(16, 4))
        self._v_cap = tk.StringVar(value=str(self._profile.max_buff_casts_per_minute))
        ttk.Entry(sr, textvariable=self._v_cap, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT)

        top = ttk.Frame(f, style=theme.S_FRAME)
        top.pack(fill=tk.X, padx=12, pady=4)
        ttk.Label(top, text="post-cast delay (s)", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_post_skill = tk.StringVar(value=str(self._profile.post_skill_delay))
        ttk.Entry(top, textvariable=self._v_post_skill, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(top, text="wait after precast (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(14, 4))
        self._v_precast_delay = tk.StringVar(value=str(self._profile.self_buff_precast_delay_sec))
        ttk.Entry(top, textvariable=self._v_precast_delay, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT)

        top2 = ttk.Frame(f, style=theme.S_FRAME)
        top2.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(top2, text="0x39 skill body", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_magic_payload = tk.StringVar(value=self._profile.magic_skill_payload)
        ttk.Combobox(
            top2, textvariable=self._v_magic_payload, width=6, values=("dcb", "ddd", "dcc"),
            state="readonly", style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)

        top2b = ttk.Frame(f, style=theme.S_FRAME)
        top2b.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(top2b, text="Buff C2S packet", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_buff_packet = tk.StringVar(value=normalize_buff_skill_packet(self._profile.buff_skill_packet))
        ttk.Combobox(
            top2b, textvariable=self._v_buff_packet, width=8, values=("39", "2f"),
            state="readonly", style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)

        top3 = ttk.Frame(f, style=theme.S_FRAME)
        top3.pack(fill=tk.X, padx=12, pady=(0, 4))
        ttk.Label(top3, text="Before self buff", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_self_precast = tk.StringVar(value=normalize_self_buff_precast(self._profile.self_buff_before_cast))
        ttk.Combobox(
            top3, textvariable=self._v_self_precast, width=14,
            values=("auto", "target_self", "none"), state="readonly", style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=4)

        live = ttk.LabelFrame(f, text="Live SkillList", style=theme.S_LF)
        live.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._live_skills = tk.Listbox(
            live, height=4, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        self._live_skills.pack(fill=tk.X, padx=8, pady=6)
        self._live_skills.bind("<Double-Button-1>", self._on_live_pick)

        abnlf = ttk.LabelFrame(f, text="Self effect ids (diagnostic)", style=theme.S_LF)
        abnlf.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._abn_diag = tk.Listbox(
            abnlf, height=3, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        self._abn_diag.pack(fill=tk.X, padx=8, pady=6)
        self._abn_diag.bind("<Double-Button-1>", self._on_abn_diag_pick)

        cols = (
            "#", "On", "Skill", "Name", "Every s", "Buff chk", "Target", "ObjId", "Retry s", "Learned",
        )
        tree_fr = ttk.Frame(f, style=theme.S_FRAME)
        tree_fr.pack(fill=tk.X, padx=10, pady=(0, 4))
        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings", height=8, style=theme.S_TREE)
        wds = {
            "#": 32, "On": 40, "Skill": 56, "Name": 160, "Every s": 64, "Buff chk": 72,
            "Target": 88, "ObjId": 72, "Retry s": 56, "Learned": 56,
        }
        for c in cols:
            self._tree.heading(c, text=c)
            self._tree.column(c, width=wds.get(c, 64), anchor="center")
        sb = ttk.Scrollbar(tree_fr, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_form_from_selection())

        form = ttk.LabelFrame(f, text="Rule editor (all targets)", style=theme.S_LF)
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
            r0, text="Rebuff if missing (AbnormalStatus)", variable=self._v_rebuff_missing, style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(12, 0))

        r0d = ttk.Frame(form, style=theme.S_FRAME)
        r0d.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(r0d, text="Match ids (comma, optional)", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_abnormal_match = tk.StringVar(value="")
        ttk.Entry(r0d, textvariable=self._v_abnormal_match, width=36, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=6)

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
            r1b, text="Skip precast before self buff", variable=self._v_skip_precast, style=theme.S_CHECK,
        ).pack(anchor="w", side=tk.LEFT)
        r1c = ttk.Frame(form, style=theme.S_FRAME)
        r1c.pack(fill=tk.X, padx=8, pady=2)
        self._v_shift = tk.BooleanVar(value=True)
        ttk.Checkbutton(r1c, text="Ally: shift-click to target", variable=self._v_shift, style=theme.S_CHECK).pack(
            side=tk.LEFT)
        self._v_force_ctrl = tk.BooleanVar(value=False)
        ttk.Checkbutton(r1c, text="Skill: force ctrl", variable=self._v_force_ctrl, style=theme.S_CHECK).pack(
            side=tk.LEFT, padx=(16, 0))
        self._v_force_shift = tk.BooleanVar(value=False)
        ttk.Checkbutton(r1c, text="Skill: force shift", variable=self._v_force_shift, style=theme.S_CHECK).pack(
            side=tk.LEFT, padx=(16, 0))

        r2b = ttk.Frame(f, style=theme.S_FRAME)
        r2b.pack(fill=tk.X, padx=14, pady=6)
        ttk.Button(r2b, text="Add rule", command=self._add_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r2b, text="Update selected", command=self._update_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r2b, text="Remove", command=self._remove_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r2b, text="Duplicate", command=self._duplicate_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r2b, text="Move up", command=lambda: self._move(-1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r2b, text="Move down", command=lambda: self._move(1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)

    def _skill_combo_values(self) -> list[str]:
        be = getattr(self.bot, "bot_engine", None)
        if not be or not be.world.my_skills:
            return []
        out: list[str] = []
        for sid in sorted(be.world.my_skills.keys()):
            nm = gre.resolve_skill_name(sid) or "?"
            out.append(f"{sid} — {nm}")
        return out

    def _refresh_skill_combos(self) -> None:
        vals = self._skill_combo_values()
        self._s_skill_combo.configure(values=vals)
        self._p_skill_combo.configure(values=vals)
        if vals and not self._s_skill_var.get():
            self._s_skill_var.set(vals[0])
        if vals and not self._p_skill_var.get():
            self._p_skill_var.set(vals[0])

    def _party_member_labels(self) -> list[str]:
        be = getattr(self.bot, "bot_engine", None)
        if not be:
            return []
        self._party_display_to_oid.clear()
        labels: list[str] = []
        for oid, m in sorted(be.world.party_members.items(), key=lambda x: x[1].name or ""):
            name = (m.name or "?").strip() or "?"
            lab = f"{name} ({oid})"
            self._party_display_to_oid[lab] = oid
            labels.append(lab)
        return labels

    def _member_name_for_oid(self, oid: int) -> str:
        be = getattr(self.bot, "bot_engine", None)
        if be and oid in be.world.party_members:
            return (be.world.party_members[oid].name or "?").strip() or "?"
        return str(oid)

    def _refresh_simple_trees(self) -> None:
        self._tree_self.delete(*self._tree_self.get_children())
        self._tree_party.delete(*self._tree_party.get_children())
        sn = 0
        for i, r in enumerate(self._profile.rules):
            if not buff_rule_is_self(r):
                continue
            sn += 1
            nm = gre.resolve_skill_name(r.skill_id) or "—"
            self._tree_self.insert(
                "", tk.END, iid=str(i),
                values=(
                    str(sn),
                    "yes" if r.enabled else "no",
                    str(r.skill_id),
                    nm[:32],
                    interval_display_minutes(r.interval_sec),
                    "yes" if r.rebuff_if_missing else "no",
                    self._learned_label(r),
                ),
            )
        pn = 0
        for i, r in enumerate(self._profile.rules):
            if not buff_rule_is_party_manual(r):
                continue
            pn += 1
            nm = gre.resolve_skill_name(r.skill_id) or "—"
            self._tree_party.insert(
                "", tk.END, iid=str(i),
                values=(
                    str(pn),
                    "yes" if r.enabled else "no",
                    self._member_name_for_oid(r.target_object_id),
                    str(r.skill_id),
                    nm[:28],
                    interval_display_minutes(r.interval_sec),
                    "yes" if r.rebuff_if_missing else "no",
                    self._learned_label(r),
                ),
            )

    def _refresh_all_trees(self) -> None:
        self._refresh_simple_trees()
        self._tree.delete(*self._tree.get_children())
        for i, r in enumerate(self._profile.rules):
            self._tree.insert("", tk.END, iid=str(i), values=self._row_values(i, r))

    def _selected_global_idx(self, tree: ttk.Treeview) -> int | None:
        sel = tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _sync_simple_form(self, party: bool) -> None:
        tree = self._tree_party if party else self._tree_self
        idx = self._selected_global_idx(tree)
        if idx is None:
            return
        r = self._profile.rules[idx]
        mins = interval_display_minutes(r.interval_sec)
        if party:
            be = getattr(self.bot, "bot_engine", None)
            if be and r.target_object_id in be.world.party_members:
                m = be.world.party_members[r.target_object_id]
                lab = f"{(m.name or '?').strip() or '?'} ({r.target_object_id})"
                if lab in self._party_display_to_oid:
                    self._p_member_var.set(lab)
            self._p_skill_var.set(
                next(
                    (x for x in self._p_skill_combo.cget("values") if x.split("—", 1)[0].strip() == str(r.skill_id)),
                    f"{r.skill_id} — {gre.resolve_skill_name(r.skill_id) or '?'}",
                )
            )
            self._p_minutes.set(mins)
            self._p_rebuff.set(r.rebuff_if_missing)
            self._p_en.set(r.enabled)
        else:
            self._s_skill_var.set(
                next(
                    (x for x in self._s_skill_combo.cget("values") if x.split("—", 1)[0].strip() == str(r.skill_id)),
                    f"{r.skill_id} — {gre.resolve_skill_name(r.skill_id) or '?'}",
                )
            )
            self._s_minutes.set(mins)
            self._s_rebuff.set(r.rebuff_if_missing)
            self._s_en.set(r.enabled)

    def _default_buff_rule(self, *, party_oid: int) -> BuffRule:
        return BuffRule(
            enabled=True,
            skill_id=0,
            interval_sec=1200.0,
            check_buff_skill_id=0,
            rebuff_if_missing=True,
            abnormal_match_ids=[],
            target_mode="manual" if party_oid else "self",
            target_object_id=party_oid,
            min_retry_sec=2.0,
            skip_precast_for_self=False,
            target_shift_click=True,
            skill_force_ctrl=False,
            skill_force_shift=False,
        )

    def _parse_simple_rule(self, party: bool) -> tuple[BuffRule | None, str | None]:
        if party:
            oid = self._party_display_to_oid.get(self._p_member_var.get().strip(), 0)
            if oid <= 0:
                return None, "Select a party member."
            sid = _parse_skill_combo_line(self._p_skill_var.get())
            if sid is None or sid <= 0:
                return None, "Select a skill."
            try:
                mins = float(self._p_minutes.get().strip() or "20")
            except ValueError:
                return None, "Invalid minutes."
            r = self._default_buff_rule(party_oid=oid)
            r.skill_id = sid
            r.interval_sec = interval_sec_from_minutes(mins)
            r.rebuff_if_missing = self._p_rebuff.get()
            r.enabled = self._p_en.get()
            return r, None
        sid = _parse_skill_combo_line(self._s_skill_var.get())
        if sid is None or sid <= 0:
            return None, "Select a skill."
        try:
            mins = float(self._s_minutes.get().strip() or "20")
        except ValueError:
            return None, "Invalid minutes."
        r = self._default_buff_rule(party_oid=0)
        r.skill_id = sid
        r.interval_sec = interval_sec_from_minutes(mins)
        r.rebuff_if_missing = self._s_rebuff.get()
        r.enabled = self._s_en.get()
        return r, None

    def _add_simple(self, party: bool) -> None:
        if not self._apply_globals():
            return
        r, err = self._parse_simple_rule(party)
        if err:
            messagebox.showerror("Buffs", err)
            return
        assert r is not None
        self._profile.rules.append(r)
        self._push_profile()

    def _update_simple(self, party: bool) -> None:
        tree = self._tree_party if party else self._tree_self
        idx = self._selected_global_idx(tree)
        if idx is None:
            messagebox.showinfo("Buffs", "Select a row first.")
            return
        if not self._apply_globals():
            return
        r, err = self._parse_simple_rule(party)
        if err:
            messagebox.showerror("Buffs", err)
            return
        assert r is not None
        old = self._profile.rules[idx]
        if party and not buff_rule_is_party_manual(old):
            messagebox.showerror("Buffs", "Wrong row type for Party tab.")
            return
        if not party and not buff_rule_is_self(old):
            messagebox.showerror("Buffs", "Wrong row type for Self tab.")
            return
        r.abnormal_match_ids = list(old.abnormal_match_ids)
        r.check_buff_skill_id = old.check_buff_skill_id
        r.min_retry_sec = old.min_retry_sec
        r.skip_precast_for_self = old.skip_precast_for_self
        r.target_shift_click = old.target_shift_click
        r.skill_force_ctrl = old.skill_force_ctrl
        r.skill_force_shift = old.skill_force_shift
        self._profile.rules[idx] = r
        self._push_profile()

    def _remove_simple(self, party: bool) -> None:
        tree = self._tree_party if party else self._tree_self
        idx = self._selected_global_idx(tree)
        if idx is None:
            return
        r = self._profile.rules[idx]
        if party and not buff_rule_is_party_manual(r):
            return
        if not party and not buff_rule_is_self(r):
            return
        del self._profile.rules[idx]
        self._push_profile()

    def _move_simple(self, party: bool, delta: int) -> None:
        filt = buff_filtered_indices(self._profile.rules, party=party)
        tree = self._tree_party if party else self._tree_self
        idx = self._selected_global_idx(tree)
        if idx is None:
            return
        try:
            pos = filt.index(idx)
        except ValueError:
            return
        j = pos + delta
        if j < 0 or j >= len(filt):
            return
        other = filt[j]
        self._profile.rules[idx], self._profile.rules[other] = (
            self._profile.rules[other], self._profile.rules[idx])
        self._push_profile()
        self._scroll.after(0, lambda: tree.selection_set(str(other)))

    def _hint_skill(self) -> None:
        try:
            n = _parse_int_entry(self._v_skill.get())
        except ValueError:
            self._id_hint.set("")
            return
        self._id_hint.set(gre.format_skill_choice(n))

    def _on_abn_diag_pick(self, _evt=None) -> None:
        sel = self._abn_diag.curselection()
        if not sel:
            return
        val = self._abn_diag.get(sel[0]).strip()
        if not val:
            return
        cur = self._v_abnormal_match.get().strip()
        self._v_abnormal_match.set(f"{cur}, {val}" if cur else val)

    def _duplicate_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Buffs", "Select a rule row first.")
            return
        idx = int(sel[0])
        r = self._profile.rules[idx]
        self._profile.rules.insert(
            idx + 1,
            replace(r, abnormal_match_ids=list(r.abnormal_match_ids)),
        )
        self._push_profile()

    def _tick_live(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        self._abn_diag.delete(0, tk.END)
        if be and be.world.me.object_id:
            for sid in sorted(be.world.abnormal_skill_ids_for_object(be.world.me.object_id)):
                self._abn_diag.insert(tk.END, str(sid))
        elif not be:
            self._abn_diag.insert(tk.END, "(no session)")
        else:
            self._abn_diag.insert(tk.END, "(no char oid)")
        self._live_skills.delete(0, tk.END)
        if not be:
            self._live_skills.insert(tk.END, "(no session)")
        elif not be.world.my_skills:
            self._live_skills.insert(tk.END, "(empty)")
        else:
            for sid in sorted(be.world.my_skills.keys()):
                lv = be.world.my_skills[sid]
                nm = gre.resolve_skill_name(sid) or "?"
                self._live_skills.insert(tk.END, f"{sid}  L{lv}  —  {nm}")
        plabs = self._party_member_labels()
        self._p_member_combo.configure(values=plabs)
        if plabs and self._p_member_var.get() not in plabs:
            self._p_member_var.set(plabs[0])
        self._refresh_skill_combos()
        self._refresh_learned_columns()
        gp = getattr(self.bot, "game_proxy", None)
        sess = gp.session if gp else None
        st = tk.NORMAL if (sess and sess.crypto_initialized) else tk.DISABLED
        self._btn_buff_save.config(state=st)
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

    def _refresh_learned_columns(self) -> None:
        for i, r in enumerate(self._profile.rules):
            iid = str(i)
            if self._tree.exists(iid):
                self._tree.set(iid, "Learned", self._learned_label(r))
                self._tree.set(iid, "Buff chk", _abn_id_display(r))
        for iid in self._tree_self.get_children():
            r = self._profile.rules[int(iid)]
            self._tree_self.set(iid, "Learned", self._learned_label(r))
        for iid in self._tree_party.get_children():
            r = self._profile.rules[int(iid)]
            self._tree_party.set(iid, "Learned", self._learned_label(r))

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
            self._profile.self_buff_precast_delay_sec = float(self._v_precast_delay.get().strip() or 0.35)
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

    def _update_path_hint(self) -> None:
        cn = self._character_name_for_config()
        p = resolve_buff_profile_write_path(character_name=cn)
        self._path_hint.configure(text=f"Save: {p.name}")

    def _save_file(self) -> None:
        if not self._apply_globals():
            return
        cn = self._character_name_for_config()
        try:
            save_buff_profile(self._profile, character_name=cn)
        except (OSError, TypeError, ValueError) as exc:
            _log.error("Buff profile save failed: %s", exc)
            messagebox.showerror("Buffs", f"Save failed: {exc}")
            return
        self._update_path_hint()
        messagebox.showinfo("Buffs", f"Saved {len(self._profile.rules)} rules.")

    def _reload_file(self) -> None:
        cb = getattr(self.bot, "reload_buff_profile_from_disk", None)
        if cb:
            self._profile = cb()
        else:
            self._profile = self._load_profile_for_ui()
        self._v_prof_en.set(self._profile.enabled)
        self._v_tick.set(str(self._profile.maintenance_tick_sec))
        self._v_pause_combat.set(self._profile.pause_while_auto_combat_engaged)
        self._v_cap.set(str(self._profile.max_buff_casts_per_minute))
        self._v_post_skill.set(str(self._profile.post_skill_delay))
        self._v_precast_delay.set(str(self._profile.self_buff_precast_delay_sec))
        self._v_magic_payload.set(self._profile.magic_skill_payload)
        self._v_buff_packet.set(normalize_buff_skill_packet(self._profile.buff_skill_packet))
        self._v_self_precast.set(normalize_self_buff_precast(self._profile.self_buff_before_cast))
        self._update_path_hint()
        self._push_profile()

    def _push_profile(self) -> None:
        if not self._apply_globals():
            return
        self._refresh_all_trees()
        cb = getattr(self.bot, "apply_buff_profile", None)
        if cb:
            cb(self._profile)
