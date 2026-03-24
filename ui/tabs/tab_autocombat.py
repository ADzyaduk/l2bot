"""Auto combat — rule list with skill/item names from static reference JSON."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from core import game_reference as gre
from engine.buff_profile import normalize_target_cancel_payload
from engine.combat_profile import CombatRule, CombatProfile, load_profile, save_profile
from ui import theme
from ui.scrollframe import ScrolledFrame


class AutoCombatTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._profile = load_profile()
        self._scroll = ScrolledFrame(parent)
        self.frame = self._scroll
        self._build()

    def _build(self) -> None:
        f = self._scroll.content
        ttk.Label(f, text="Auto combat profile", style=theme.S_TITLE).pack(anchor="w", padx=14, pady=(12, 4))
        ttk.Label(
            f,
            text="Rules are evaluated top → bottom; first match fires per tick. Skills use datapack skillId. "
            "Items use template itemId — the bot maps them to inventory objectId after ItemList (open inventory once). "
            "Rebuff: set «buff missing» to a skill id from AbnormalStatusUpdate so the rule runs only when that buff is absent.",
            style=theme.S_LABEL_MUTED,
            wraplength=760,
        ).pack(anchor="w", padx=14, pady=(0, 4))
        ttk.Label(
            f,
            text="Skill names in this UI come from data/skills_en.json (static). The server sends SkillList with skill id + level only — "
            "no names in the packet. Cross-check ids with your learned list below.",
            style=theme.S_LABEL_MUTED,
            wraplength=760,
        ).pack(anchor="w", padx=14, pady=(0, 6))

        rec = ttk.LabelFrame(f, text="Recovery (sit / HP / MP)", style=theme.S_LF)
        rec.pack(fill=tk.X, padx=10, pady=(0, 6))
        rc0 = ttk.Frame(rec, style=theme.S_FRAME)
        rc0.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(rc0, text="In combat: sit if HP below %", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_combat_sit_hp = tk.StringVar(value=str(self._profile.combat_sit_hp_below_pct))
        ttk.Entry(rc0, textvariable=self._v_combat_sit_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc0, text="stand when HP ≥ %", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 0))
        self._v_combat_stand_hp = tk.StringVar(value=str(self._profile.combat_stand_hp_pct))
        ttk.Entry(rc0, textvariable=self._v_combat_stand_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            rc0,
            text="(not used while you have a target — sitting mid-fight caused stuck behavior; use post-kill sit or item rules)",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT, padx=(12, 0))

        rc1 = ttk.Frame(rec, style=theme.S_FRAME)
        rc1.pack(fill=tk.X, padx=8, pady=2)
        self._v_post_kill_en = tk.BooleanVar(value=self._profile.post_kill_sit_enabled)
        ttk.Checkbutton(
            rc1, text="After kill: sit to regen if HP below %", variable=self._v_post_kill_en, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        self._v_post_kill_sit_hp = tk.StringVar(value=str(self._profile.post_kill_sit_hp_below_pct))
        ttk.Entry(rc1, textvariable=self._v_post_kill_sit_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc1, text="stand when HP ≥ %", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        self._v_post_kill_stand_hp = tk.StringVar(value=str(self._profile.post_kill_stand_hp_pct))
        ttk.Entry(rc1, textvariable=self._v_post_kill_stand_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        rc2 = ttk.Frame(rec, style=theme.S_FRAME)
        rc2.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(
            rc2,
            text="Optional MP while sitting: set both > 0 to also wait until MP ≥ target before standing (HP target still required).",
            style=theme.S_LABEL_MUTED, wraplength=720,
        ).pack(anchor="w")
        rc2b = ttk.Frame(rec, style=theme.S_FRAME)
        rc2b.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(rc2b, text="MP gate: first field & second both > 0 enables. Target MP ≥ %", style=theme.S_LABEL).pack(
            side=tk.LEFT)
        self._v_rec_sit_mp = tk.StringVar(value=str(self._profile.recovery_sit_mp_below_pct))
        ttk.Entry(rc2b, textvariable=self._v_rec_sit_mp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._v_rec_stand_mp = tk.StringVar(value=str(self._profile.recovery_stand_mp_pct))
        ttk.Entry(rc2b, textvariable=self._v_rec_stand_mp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc2b, text="Max sit wait (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(14, 0))
        self._v_rec_max_wait = tk.StringVar(value=str(self._profile.recovery_max_wait_sec))
        ttk.Entry(rc2b, textvariable=self._v_rec_max_wait, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        loot_fr = ttk.Frame(rec, style=theme.S_FRAME)
        loot_fr.pack(fill=tk.X, padx=8, pady=(2, 4))
        self._v_auto_loot = tk.BooleanVar(value=self._profile.auto_loot)
        ttk.Checkbutton(loot_fr, text="Auto loot", variable=self._v_auto_loot, style=theme.S_CHECK).pack(side=tk.LEFT)
        ttk.Label(loot_fr, text="pickup range", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 4))
        self._v_loot_range = tk.StringVar(value=str(self._profile.loot_range))
        ttk.Entry(loot_fr, textvariable=self._v_loot_range, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=(0, 4))

        pkt_fr = ttk.Frame(rec, style=theme.S_FRAME)
        pkt_fr.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(pkt_fr, text="After kill: drop target (0x37) payload", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._v_tgt_cancel = tk.StringVar(value=self._profile.target_cancel_payload)
        ttk.Combobox(
            pkt_fr,
            textvariable=self._v_tgt_cancel,
            width=5,
            values=("h", "d"),
            state="readonly",
            style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(
            pkt_fr,
            text="h = WORD(0), two bytes · d = DWORD(0), four bytes",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT, padx=(4, 0))

        sit_sf = ttk.LabelFrame(f, text="Post-kill recovery sit — safety", style=theme.S_LF)
        sit_sf.pack(fill=tk.X, padx=10, pady=(0, 6))
        ss0 = ttk.Frame(sit_sf, style=theme.S_FRAME)
        ss0.pack(fill=tk.X, padx=8, pady=(6, 2))
        self._v_never_sit_tgt = tk.BooleanVar(value=self._profile.never_sit_while_target)
        ttk.Checkbutton(
            ss0,
            text="Never sit while a living attackable mob is still targeted",
            variable=self._v_never_sit_tgt,
            style=theme.S_CHECK,
        ).pack(anchor="w")
        ss1 = ttk.Frame(sit_sf, style=theme.S_FRAME)
        ss1.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(
            ss1,
            text="Block recovery sit for this many seconds after you take damage (0 = off)",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        self._v_dmg_gate = tk.StringVar(value=str(self._profile.incoming_damage_sit_block_sec))
        ttk.Entry(ss1, textvariable=self._v_dmg_gate, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        tim = ttk.LabelFrame(f, text="Timing (auto-combat loop)", style=theme.S_LF)
        tim.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._v_kill_poll = tk.StringVar(value=str(self._profile.kill_poll_tick_sec))
        self._v_kill_timeout = tk.StringVar(value=str(self._profile.kill_timeout_sec))
        self._v_reattack = tk.StringVar(value=str(self._profile.reattack_interval_sec))
        self._v_reattack_sleep = tk.StringVar(value=str(self._profile.reattack_action_sleep_sec))
        self._v_pk_spawn = tk.StringVar(value=str(self._profile.post_kill_spawn_wait_sec))
        self._v_pk_loot_d = tk.StringVar(value=str(self._profile.post_kill_loot_item_delay_sec))
        self._v_pk_loot_sleep = tk.StringVar(value=str(self._profile.post_kill_loot_after_sleep_sec))
        self._v_pk_rec = tk.StringVar(value=str(self._profile.post_kill_recovery_after_stand_sec))
        self._v_between = tk.StringVar(value=str(self._profile.between_targets_sleep_sec))
        self._v_idle_nomobs = tk.StringVar(value=str(self._profile.idle_no_mobs_sleep_sec))
        self._v_open_loot = tk.StringVar(value=str(self._profile.open_combat_pre_loot_sleep_sec))
        self._v_idle_loot_d = tk.StringVar(value=str(self._profile.idle_loot_item_delay_sec))

        def _tim_row(parent: ttk.Frame, pairs: list[tuple[str, tk.StringVar]]) -> None:
            row = ttk.Frame(parent, style=theme.S_FRAME)
            row.pack(fill=tk.X, padx=8, pady=2)
            for lab, var in pairs:
                ttk.Label(row, text=lab, style=theme.S_LABEL).pack(side=tk.LEFT)
                ttk.Entry(row, textvariable=var, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=(2, 14))

        _tim_row(
            tim,
            [
                ("Kill poll s", self._v_kill_poll),
                ("Kill timeout s", self._v_kill_timeout),
                ("Reattack s", self._v_reattack),
                ("Reattack act s", self._v_reattack_sleep),
            ],
        )
        _tim_row(
            tim,
            [
                ("Post-kill spawn wait", self._v_pk_spawn),
                ("Loot item delay", self._v_pk_loot_d),
                ("After loot sleep", self._v_pk_loot_sleep),
                ("After stand sleep", self._v_pk_rec),
            ],
        )
        _tim_row(
            tim,
            [
                ("Between targets", self._v_between),
                ("Idle no mobs", self._v_idle_nomobs),
                ("Open combat pre-loot", self._v_open_loot),
                ("Idle loot delay", self._v_idle_loot_d),
            ],
        )

        live = ttk.LabelFrame(f, text="Live from game (updates every ~2s)", style=theme.S_LF)
        live.pack(fill=tk.X, padx=10, pady=(0, 6))
        live_row = ttk.Frame(live, style=theme.S_FRAME)
        live_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        lf_sk = ttk.LabelFrame(live_row, text="SkillList → my_skills", style=theme.S_LF)
        lf_sk.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self._live_skills = tk.Listbox(
            lf_sk, height=5, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        sb_ls = ttk.Scrollbar(lf_sk, orient=tk.VERTICAL, command=self._live_skills.yview)
        self._live_skills.config(yscrollcommand=sb_ls.set)
        self._live_skills.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_ls.pack(side=tk.RIGHT, fill=tk.Y)
        lf_inv = ttk.LabelFrame(live_row, text="ItemList → inventory (open inv once)", style=theme.S_LF)
        lf_inv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._live_inv = tk.Listbox(
            lf_inv, height=5, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        sb_li = ttk.Scrollbar(lf_inv, orient=tk.VERTICAL, command=self._live_inv.yview)
        self._live_inv.config(yscrollcommand=sb_li.set)
        self._live_inv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_li.pack(side=tk.RIGHT, fill=tk.Y)

        self._learned_var = tk.StringVar(value="Skills from server (SkillList packet): —")
        ttk.Label(f, textvariable=self._learned_var, style=theme.S_LABEL_MUTED, font=theme.FONT_MONO).pack(
            anchor="w", padx=14, pady=(0, 4))

        rot = ttk.LabelFrame(f, text="Skill rotation", style=theme.S_LF)
        rot.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        tree_fr = ttk.Frame(rot, style=theme.S_FRAME)
        tree_fr.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 2))
        cols = (
            "#", "Type", "ID", "Name", "Learned",
            "HP<%", "MP<%", "HP≥%", "MP≥%", "Combat", "CD s", "Miss buff",
        )
        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings", height=10, style=theme.S_TREE)
        widths = {
            "#": 32, "Type": 52, "ID": 56, "Name": 160, "Learned": 48,
            "HP<%": 44, "MP<%": 44, "HP≥%": 44, "MP≥%": 44,
            "Combat": 48, "CD s": 40, "Miss buff": 64,
        }
        for c in cols:
            self._tree.heading(c, text=c)
            self._tree.column(c, width=widths[c])
        sb = ttk.Scrollbar(tree_fr, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_form_from_selection())

        form = ttk.LabelFrame(rot, text="Rule builder", style=theme.S_LF)
        form.pack(fill=tk.X, padx=6, pady=(0, 6))

        r0 = ttk.Frame(form, style=theme.S_FRAME)
        r0.pack(fill=tk.X, padx=8, pady=4)
        self._kind = tk.StringVar(value="skill")
        ttk.Radiobutton(
            r0, text="Skill", variable=self._kind, value="skill", style=theme.S_RADIO,
            command=self._on_kind_change,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            r0, text="Item template", variable=self._kind, value="item", style=theme.S_RADIO,
            command=self._on_kind_change,
        ).pack(side=tk.LEFT, padx=14)

        r1 = ttk.Frame(form, style=theme.S_FRAME)
        r1.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(r1, text="Search:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._search = tk.StringVar()
        self._search.trace_add("write", lambda *_: self._refresh_pick_list())
        ttk.Entry(r1, textvariable=self._search, width=22, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._only_learned_pick = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            r1,
            text="Only skills from SkillList",
            variable=self._only_learned_pick,
            command=self._refresh_pick_list,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(r1, text="Numeric ID:", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        self._rid = tk.StringVar(value="3")
        self._rid.trace_add("write", lambda *_: self._update_id_hint())
        ttk.Entry(r1, textvariable=self._rid, width=10, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._id_hint = tk.StringVar()
        ttk.Label(r1, textvariable=self._id_hint, style=theme.S_LABEL_MUTED).pack(side=tk.LEFT, padx=6)

        lb_fr = ttk.Frame(form, style=theme.S_FRAME)
        lb_fr.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._pick = tk.Listbox(
            lb_fr, height=5, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            selectbackground=theme.COL_ACCENT_DIM, font=theme.FONT_MONO, exportselection=False,
        )
        sb2 = ttk.Scrollbar(lb_fr, orient=tk.VERTICAL, command=self._pick.yview)
        self._pick.config(yscrollcommand=sb2.set)
        self._pick.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._pick.bind("<<ListboxSelect>>", self._on_pick)

        r2 = ttk.Frame(form, style=theme.S_FRAME)
        r2.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(r2, text="HP below % (0=ignore):", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._hp = tk.StringVar(value="0")
        ttk.Entry(r2, textvariable=self._hp, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r2, text="MP below %:", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 0))
        self._mp = tk.StringVar(value="0")
        ttk.Entry(r2, textvariable=self._mp, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        self._only_combat = tk.BooleanVar(value=True)
        ttk.Checkbutton(r2, text="Only in combat", variable=self._only_combat, style=theme.S_CHECK).pack(side=tk.LEFT, padx=14)
        ttk.Label(r2, text="Cooldown s:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._cd = tk.StringVar(value="0")
        ttk.Entry(r2, textvariable=self._cd, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        r2m = ttk.Frame(form, style=theme.S_FRAME)
        r2m.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(
            r2m,
            text="HP min % (0=off, need HP≥ for rule — e.g. don’t nuke while critical):",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        self._hp_min = tk.StringVar(value="0")
        ttk.Entry(r2m, textvariable=self._hp_min, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r2m, text="MP min % (0=off — e.g. Mortal Blow only if mana ≥):", style=theme.S_LABEL).pack(
            side=tk.LEFT, padx=(10, 0))
        self._mp_min = tk.StringVar(value="0")
        ttk.Entry(r2m, textvariable=self._mp_min, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        r2b = ttk.Frame(form, style=theme.S_FRAME)
        r2b.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(
            r2b,
            text="Rebuff: fire only if buff skill id is missing (0 = off):",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        self._rebuff = tk.StringVar(value="0")
        ttk.Entry(r2b, textvariable=self._rebuff, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            r2b,
            text="id from server buff list (AbnormalStatusUpdate)",
            style=theme.S_LABEL_MUTED,
        ).pack(side=tk.LEFT, padx=4)

        r3 = ttk.Frame(form, style=theme.S_FRAME)
        r3.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(r3, text="Delays: after target (s)", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._d_target = tk.StringVar(value=str(self._profile.post_target_delay))
        ttk.Entry(r3, textvariable=self._d_target, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r3, text="after skill (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        self._d_skill = tk.StringVar(value=str(self._profile.post_skill_delay))
        ttk.Entry(r3, textvariable=self._d_skill, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        r4 = ttk.Frame(f, style=theme.S_FRAME)
        r4.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(r4, text="Add rule", command=self._add_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r4, text="Update selected", command=self._update_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r4, text="Remove", command=self._remove_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r4, text="Move up", command=lambda: self._move(-1), style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r4, text="Move down", command=lambda: self._move(1), style=theme.S_BTN).pack(side=tk.LEFT, padx=3)
        ttk.Button(r4, text="Save to file", command=self._save_file, style=theme.S_BTN).pack(side=tk.LEFT, padx=12)
        ttk.Button(r4, text="Reload file", command=self._reload_file, style=theme.S_BTN).pack(side=tk.LEFT, padx=3)

        self._on_kind_change()
        self._refresh_tree()
        self._push_profile()
        self._tick_learned()

    def _tick_learned(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        n = len(be.world.my_skills) if be else 0
        self._learned_var.set(
            f"Skills from server (SkillList packet, ids only — names from data/skills_en.json): {n}"
        )
        self._refresh_learned_column()
        self._refresh_live_lists(be)
        self._scroll.after(2000, self._tick_learned)

    def _refresh_live_lists(self, be) -> None:
        self._live_skills.delete(0, tk.END)
        self._live_inv.delete(0, tk.END)
        if not be:
            self._live_skills.insert(tk.END, "(connect game client through proxy — no session)")
            self._live_inv.insert(tk.END, "(same)")
            return
        w = be.world
        if not w.my_skills:
            self._live_skills.insert(tk.END, "(empty — enter world / wait for SkillList)")
        else:
            for sid in sorted(w.my_skills.keys()):
                lv = w.my_skills[sid]
                nm = gre.resolve_skill_name(sid) or "?"
                self._live_skills.insert(tk.END, f"{sid}  L{lv}  —  {nm}")
        if not w.inventory_by_object:
            self._live_inv.insert(
                tk.END, "(empty — open inventory in game so ItemList is sent)",
            )
        else:
            for oid, (tid, cnt) in sorted(w.inventory_by_object.items()):
                nm = gre.resolve_item_name(tid) or "?"
                self._live_inv.insert(
                    tk.END, f"0x{oid:X}  tpl={tid} x{cnt}  {nm}",
                )

    def _on_kind_change(self) -> None:
        self._refresh_pick_list()
        self._update_id_hint()

    def _update_id_hint(self) -> None:
        try:
            n = int(self._rid.get().strip())
        except ValueError:
            self._id_hint.set("")
            return
        if self._kind.get() == "skill":
            self._id_hint.set(gre.format_skill_choice(n))
        else:
            self._id_hint.set(gre.format_item_choice(n))

    def _refresh_pick_list(self) -> None:
        self._pick.delete(0, tk.END)
        q = self._search.get()
        if self._kind.get() == "skill":
            pairs = gre.search_skills(q, 200)
            if self._only_learned_pick.get():
                be = getattr(self.bot, "bot_engine", None)
                learned = be.world.my_skills if be else {}
                if learned:
                    pairs = [(sid, name) for sid, name in pairs if sid in learned]
        else:
            pairs = gre.search_items(q, 150)
        for sid, name in pairs:
            self._pick.insert(tk.END, f"{sid}: {name}")

    def _on_pick(self, _evt=None) -> None:
        sel = self._pick.curselection()
        if not sel:
            return
        line = self._pick.get(sel[0])
        sid = int(line.split(":", 1)[0].strip())
        self._rid.set(str(sid))

    def _learned_label(self, r: CombatRule) -> str:
        if r.kind != "skill":
            return "—"
        be = getattr(self.bot, "bot_engine", None)
        if not be or not be.world.my_skills:
            return "?"
        return "yes" if r.skill_id in be.world.my_skills else "no"

    def _row_values(self, i: int, r: CombatRule) -> tuple:
        if r.kind == "skill":
            nid = r.skill_id
            nm = gre.resolve_skill_name(nid) or "—"
        else:
            nid = r.item_id
            nm = gre.resolve_item_name(nid) or "—"
        return (
            str(i + 1),
            r.kind,
            str(nid),
            nm,
            self._learned_label(r),
            f"{r.hp_below_pct:g}" if r.hp_below_pct else "—",
            f"{r.mp_below_pct:g}" if r.mp_below_pct else "—",
            f"{r.hp_min_pct:g}" if r.hp_min_pct else "—",
            f"{r.mp_min_pct:g}" if r.mp_min_pct else "—",
            "yes" if r.only_in_combat else "no",
            f"{r.cooldown_sec:g}" if r.cooldown_sec else "—",
            str(r.rebuff_missing_skill_id) if r.rebuff_missing_skill_id else "—",
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

    def _sync_form_from_selection(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        r = self._profile.rules[idx]
        self._kind.set(r.kind)
        self._rid.set(str(r.skill_id if r.kind == "skill" else r.item_id))
        self._hp.set(str(r.hp_below_pct) if r.hp_below_pct else "0")
        self._mp.set(str(r.mp_below_pct) if r.mp_below_pct else "0")
        self._hp_min.set(str(r.hp_min_pct) if r.hp_min_pct else "0")
        self._mp_min.set(str(r.mp_min_pct) if r.mp_min_pct else "0")
        self._only_combat.set(r.only_in_combat)
        self._cd.set(str(r.cooldown_sec) if r.cooldown_sec else "0")
        self._rebuff.set(str(r.rebuff_missing_skill_id) if r.rebuff_missing_skill_id else "0")
        self._d_target.set(str(self._profile.post_target_delay))
        self._d_skill.set(str(self._profile.post_skill_delay))
        self._on_kind_change()

    def _parse_rule_from_form(self) -> CombatRule | None:
        try:
            rid = int(self._rid.get().strip())
        except ValueError:
            messagebox.showerror("Auto combat", "Enter a numeric skill or item id.")
            return None
        try:
            hp = float(self._hp.get() or 0)
            mp = float(self._mp.get() or 0)
            hp_min = float(self._hp_min.get() or 0)
            mp_min = float(self._mp_min.get() or 0)
            cd = float(self._cd.get() or 0)
            rebuff = int(float(self._rebuff.get().strip() or 0))
        except ValueError:
            messagebox.showerror("Auto combat", "Invalid HP/MP/min/cooldown/rebuff numbers.")
            return None
        k = self._kind.get()
        if k == "skill":
            return CombatRule(
                kind="skill", skill_id=rid, item_id=0,
                hp_below_pct=hp, mp_below_pct=mp,
                hp_min_pct=hp_min, mp_min_pct=mp_min,
                only_in_combat=self._only_combat.get(), cooldown_sec=cd,
                rebuff_missing_skill_id=rebuff,
            )
        return CombatRule(
            kind="item", skill_id=0, item_id=rid,
            hp_below_pct=hp, mp_below_pct=mp,
            hp_min_pct=hp_min, mp_min_pct=mp_min,
            only_in_combat=self._only_combat.get(), cooldown_sec=cd,
            rebuff_missing_skill_id=rebuff,
        )

    def _apply_globals_to_profile(self) -> bool:
        try:
            self._profile.post_target_delay = float(self._d_target.get())
            self._profile.post_skill_delay = float(self._d_skill.get())
            self._profile.combat_sit_hp_below_pct = float(self._v_combat_sit_hp.get())
            self._profile.combat_stand_hp_pct = float(self._v_combat_stand_hp.get())
            self._profile.post_kill_sit_enabled = self._v_post_kill_en.get()
            self._profile.post_kill_sit_hp_below_pct = float(self._v_post_kill_sit_hp.get())
            self._profile.post_kill_stand_hp_pct = float(self._v_post_kill_stand_hp.get())
            self._profile.recovery_sit_mp_below_pct = float(self._v_rec_sit_mp.get())
            self._profile.recovery_stand_mp_pct = float(self._v_rec_stand_mp.get())
            self._profile.recovery_max_wait_sec = float(self._v_rec_max_wait.get())
            self._profile.auto_loot = self._v_auto_loot.get()
            self._profile.loot_range = float(self._v_loot_range.get())
            self._profile.target_cancel_payload = normalize_target_cancel_payload(self._v_tgt_cancel.get())
            self._v_tgt_cancel.set(self._profile.target_cancel_payload)
            self._profile.never_sit_while_target = self._v_never_sit_tgt.get()
            self._profile.incoming_damage_sit_block_sec = float(self._v_dmg_gate.get())
            self._profile.kill_poll_tick_sec = float(self._v_kill_poll.get())
            self._profile.kill_timeout_sec = float(self._v_kill_timeout.get())
            self._profile.reattack_interval_sec = float(self._v_reattack.get())
            self._profile.reattack_action_sleep_sec = float(self._v_reattack_sleep.get())
            self._profile.post_kill_spawn_wait_sec = float(self._v_pk_spawn.get())
            self._profile.post_kill_loot_item_delay_sec = float(self._v_pk_loot_d.get())
            self._profile.post_kill_loot_after_sleep_sec = float(self._v_pk_loot_sleep.get())
            self._profile.post_kill_recovery_after_stand_sec = float(self._v_pk_rec.get())
            self._profile.between_targets_sleep_sec = float(self._v_between.get())
            self._profile.idle_no_mobs_sleep_sec = float(self._v_idle_nomobs.get())
            self._profile.open_combat_pre_loot_sleep_sec = float(self._v_open_loot.get())
            self._profile.idle_loot_item_delay_sec = float(self._v_idle_loot_d.get())
        except ValueError:
            messagebox.showerror("Auto combat", "Invalid number in delays, recovery, loot, or timing fields.")
            return False
        return True

    def _add_rule(self) -> None:
        if not self._apply_globals_to_profile():
            return
        r = self._parse_rule_from_form()
        if r is None:
            return
        self._profile.rules.append(r)
        self._push_profile()

    def _update_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Auto combat", "Select a rule row first.")
            return
        if not self._apply_globals_to_profile():
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
        idx = int(sel[0])
        del self._profile.rules[idx]
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
        if not self._apply_globals_to_profile():
            return
        save_profile(self._profile)
        messagebox.showinfo("Auto combat", f"Saved {len(self._profile.rules)} rules.")

    def _reload_file(self) -> None:
        self._profile = load_profile()
        self._d_target.set(str(self._profile.post_target_delay))
        self._d_skill.set(str(self._profile.post_skill_delay))
        self._v_combat_sit_hp.set(str(self._profile.combat_sit_hp_below_pct))
        self._v_combat_stand_hp.set(str(self._profile.combat_stand_hp_pct))
        self._v_post_kill_en.set(self._profile.post_kill_sit_enabled)
        self._v_post_kill_sit_hp.set(str(self._profile.post_kill_sit_hp_below_pct))
        self._v_post_kill_stand_hp.set(str(self._profile.post_kill_stand_hp_pct))
        self._v_rec_sit_mp.set(str(self._profile.recovery_sit_mp_below_pct))
        self._v_rec_stand_mp.set(str(self._profile.recovery_stand_mp_pct))
        self._v_rec_max_wait.set(str(self._profile.recovery_max_wait_sec))
        self._v_auto_loot.set(self._profile.auto_loot)
        self._v_loot_range.set(str(self._profile.loot_range))
        self._v_tgt_cancel.set(self._profile.target_cancel_payload)
        self._v_never_sit_tgt.set(self._profile.never_sit_while_target)
        self._v_dmg_gate.set(str(self._profile.incoming_damage_sit_block_sec))
        self._v_kill_poll.set(str(self._profile.kill_poll_tick_sec))
        self._v_kill_timeout.set(str(self._profile.kill_timeout_sec))
        self._v_reattack.set(str(self._profile.reattack_interval_sec))
        self._v_reattack_sleep.set(str(self._profile.reattack_action_sleep_sec))
        self._v_pk_spawn.set(str(self._profile.post_kill_spawn_wait_sec))
        self._v_pk_loot_d.set(str(self._profile.post_kill_loot_item_delay_sec))
        self._v_pk_loot_sleep.set(str(self._profile.post_kill_loot_after_sleep_sec))
        self._v_pk_rec.set(str(self._profile.post_kill_recovery_after_stand_sec))
        self._v_between.set(str(self._profile.between_targets_sleep_sec))
        self._v_idle_nomobs.set(str(self._profile.idle_no_mobs_sleep_sec))
        self._v_open_loot.set(str(self._profile.open_combat_pre_loot_sleep_sec))
        self._v_idle_loot_d.set(str(self._profile.idle_loot_item_delay_sec))
        self._push_profile()

    def _push_profile(self) -> None:
        self._refresh_tree()
        cb = getattr(self.bot, "apply_combat_profile", None)
        if cb:
            cb(self._profile)
