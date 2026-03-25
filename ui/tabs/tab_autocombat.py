"""Auto combat — rule list with skill/item names from static reference JSON."""
from __future__ import annotations

import logging
from dataclasses import replace
import tkinter as tk
from tkinter import messagebox, ttk

from core import game_reference as gre
from engine.buff_profile import (
    normalize_buff_skill_packet,
    normalize_magic_skill_payload,
    normalize_target_cancel_payload,
)
from engine.character_config import resolve_combat_profile_write_path
from engine.combat_profile import CombatRule, CombatProfile, load_profile, save_profile
from ui import theme
from ui.profile_simple import combat_when_summary
from ui.scrollframe import ScrolledFrame

_log = logging.getLogger(__name__)


class AutoCombatTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._profile = self._load_profile_for_ui()
        self._scroll = ScrolledFrame(parent)
        self.frame = self._scroll
        self._build()

    def _character_name_for_config(self) -> str | None:
        be = getattr(self.bot, "bot_engine", None)
        if not be:
            return None
        return be.world.me.name or ""

    def _load_profile_for_ui(self) -> CombatProfile:
        cn = self._character_name_for_config()
        if cn is None:
            return load_profile(None)
        return load_profile(character_name=cn)

    def refresh_profile_from_disk(self) -> None:
        """Reload JSON from disk into this tab (e.g. after UserInfo switches character)."""
        self._reload_file()

    def _ensure_combat_vars(self) -> None:
        if getattr(self, "_ac_vars_ok", False):
            return
        p = self._profile
        self._v_combat_sit_hp = tk.StringVar(value=str(p.combat_sit_hp_below_pct))
        self._v_combat_stand_hp = tk.StringVar(value=str(p.combat_stand_hp_pct))
        self._v_post_kill_en = tk.BooleanVar(value=p.post_kill_sit_enabled)
        self._v_post_kill_sit_hp = tk.StringVar(value=str(p.post_kill_sit_hp_below_pct))
        self._v_post_kill_stand_hp = tk.StringVar(value=str(p.post_kill_stand_hp_pct))
        self._v_rec_sit_mp = tk.StringVar(value=str(p.recovery_sit_mp_below_pct))
        self._v_rec_stand_mp = tk.StringVar(value=str(p.recovery_stand_mp_pct))
        self._v_rec_max_wait = tk.StringVar(value=str(p.recovery_max_wait_sec))
        self._v_auto_loot = tk.BooleanVar(value=p.auto_loot)
        self._v_loot_range = tk.StringVar(value=str(p.loot_range))
        self._v_tgt_cancel = tk.StringVar(value=p.target_cancel_payload)
        self._v_combat_skill_pkt = tk.StringVar(value=normalize_buff_skill_packet(p.combat_skill_packet))
        self._v_magic_skill_payload = tk.StringVar(value=normalize_magic_skill_payload(p.magic_skill_payload))
        self._v_never_sit_tgt = tk.BooleanVar(value=p.never_sit_while_target)
        self._v_dmg_gate = tk.StringVar(value=str(p.incoming_damage_sit_block_sec))
        self._v_cwt_sit_raw = tk.StringVar(value=str(p.recovery_change_wait_type_sit_raw))
        self._v_rec_stand_toggles = tk.StringVar(value=str(p.recovery_stand_toggle_attempts))
        self._v_kill_poll = tk.StringVar(value=str(p.kill_poll_tick_sec))
        self._v_kill_timeout = tk.StringVar(value=str(p.kill_timeout_sec))
        self._v_reattack = tk.StringVar(value=str(p.reattack_interval_sec))
        self._v_reattack_sleep = tk.StringVar(value=str(p.reattack_action_sleep_sec))
        self._v_pk_spawn = tk.StringVar(value=str(p.post_kill_spawn_wait_sec))
        self._v_pk_loot_d = tk.StringVar(value=str(p.post_kill_loot_item_delay_sec))
        self._v_pk_loot_sleep = tk.StringVar(value=str(p.post_kill_loot_after_sleep_sec))
        self._v_pk_rec = tk.StringVar(value=str(p.post_kill_recovery_after_stand_sec))
        self._v_between = tk.StringVar(value=str(p.between_targets_sleep_sec))
        self._v_idle_nomobs = tk.StringVar(value=str(p.idle_no_mobs_sleep_sec))
        self._v_open_loot = tk.StringVar(value=str(p.open_combat_pre_loot_sleep_sec))
        self._v_idle_loot_d = tk.StringVar(value=str(p.idle_loot_item_delay_sec))
        self._v_prefer_aggro = tk.BooleanVar(value=p.prefer_aggro_mobs)
        self._v_retain_dist = tk.StringVar(value=str(p.retain_current_target_max_dist))
        self._v_npc_blacklist = tk.StringVar(value=", ".join(str(x) for x in p.npc_blacklist_ids))
        self._v_whitelist_only = tk.BooleanVar(value=p.attack_only_whitelist_mobs)
        self._v_npc_whitelist = tk.StringVar(value=", ".join(str(x) for x in p.npc_whitelist_ids))
        self._v_zrange = tk.StringVar(value=str(p.target_z_range_max))
        self._v_skip_summon = tk.BooleanVar(value=p.skip_summoned_npcs)
        self._v_skill_gap = tk.StringVar(value=str(p.combat_skill_min_interval_sec))
        self._v_never_oid = tk.StringVar(value=", ".join(str(x) for x in p.never_attack_object_ids))
        self._v_party_oid = tk.StringVar(value=", ".join(str(x) for x in p.party_protect_object_ids))
        self._v_anchor_en = tk.BooleanVar(value=p.combat_anchor_leash_enabled)
        self._v_anchor_r = tk.StringVar(value=str(p.combat_anchor_leash_radius))
        self._v_anchor_idle = tk.StringVar(value=str(p.combat_anchor_reset_idle_sec))
        self._v_loot_anchor = tk.BooleanVar(value=p.loot_respect_anchor_leash)
        self._v_retarget_aggro = tk.BooleanVar(value=p.retarget_to_aggro_enabled)
        self._v_aggro_win = tk.StringVar(value=str(p.aggro_retarget_window_sec))
        self._v_rules_tick = tk.StringVar(value=str(p.combat_rules_tick_sec))
        self._v_sweep_en = tk.BooleanVar(value=p.post_kill_sweep_enabled)
        self._v_sweep_sid = tk.StringVar(value=str(p.post_kill_sweep_skill_id))
        self._v_sweep_dly = tk.StringVar(value=str(p.post_kill_sweep_delay_sec))
        self._v_idle_sit_en = tk.BooleanVar(value=p.combat_sit_while_idle_enabled)
        self._kind = tk.StringVar(value="skill")
        self._search = tk.StringVar()
        self._only_learned_pick = tk.BooleanVar(value=False)
        self._rid = tk.StringVar(value="3")
        self._id_hint = tk.StringVar()
        self._hp = tk.StringVar(value="0")
        self._mp = tk.StringVar(value="0")
        self._hp_min = tk.StringVar(value="0")
        self._mp_min = tk.StringVar(value="0")
        self._only_combat = tk.BooleanVar(value=True)
        self._fire_before_first = tk.BooleanVar(value=False)
        self._cd = tk.StringVar(value="0")
        self._rebuff = tk.StringVar(value="0")
        self._tgt_miss_abn = tk.StringVar(value="")
        self._tgt_has_abn = tk.StringVar(value="")
        self._d_target = tk.StringVar(value=str(p.post_target_delay))
        self._d_skill = tk.StringVar(value=str(p.post_skill_delay))
        self._learned_var = tk.StringVar(value="Skills from server: —")
        self._sim_kind = tk.StringVar(value="skill")
        self._sim_pick_var = tk.StringVar()
        self._sim_hp = tk.StringVar(value="0")
        self._sim_combat = tk.BooleanVar(value=True)
        self._ac_vars_ok = True

    def _toggle_adv_combat(self) -> None:
        if self._adv_show.get():
            self._adv_combat_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 8))
        else:
            self._adv_combat_frame.pack_forget()

    def _build_simple_top(self, root: tk.Widget) -> None:
        ttk.Label(root, text="Auto combat", style=theme.S_TITLE).pack(anchor="w", padx=14, pady=(14, 4))
        self._path_hint = ttk.Label(root, text="", style=theme.S_LABEL_MUTED)
        self._path_hint.pack(anchor="w", padx=14)
        self._update_path_hint()
        ttk.Label(
            root,
            text="Empty list = auto-attack only. First matching row runs each tick.",
            style=theme.S_LABEL_MUTED,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        rot = ttk.LabelFrame(root, text="Skills & items (order matters)", style=theme.S_LF)
        rot.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        cols = ("#", "Type", "Name", "When", "Lrn")
        tf = ttk.Frame(rot, style=theme.S_FRAME)
        tf.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._sim_tree = ttk.Treeview(tf, columns=cols, show="headings", height=8, style=theme.S_TREE)
        sw = {"#": 36, "Type": 52, "Name": 220, "When": 200, "Lrn": 44}
        for c in cols:
            self._sim_tree.heading(c, text=c)
            self._sim_tree.column(c, width=sw[c])
        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._sim_tree.yview)
        self._sim_tree.configure(yscrollcommand=sb.set)
        self._sim_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._sim_tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_sim_form_from_selection())

        ed = ttk.Frame(rot, style=theme.S_FRAME)
        ed.pack(fill=tk.X, padx=8, pady=6)
        ttk.Radiobutton(
            ed, text="Skill", variable=self._sim_kind, value="skill", style=theme.S_RADIO, command=self._sim_refresh_pick_combo,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            ed, text="Item", variable=self._sim_kind, value="item", style=theme.S_RADIO, command=self._sim_refresh_pick_combo,
        ).pack(side=tk.LEFT, padx=(12, 0))
        self._sim_pick_combo = ttk.Combobox(
            ed, textvariable=self._sim_pick_var, width=52, state="readonly", style=theme.S_ENTRY,
        )
        self._sim_pick_combo.pack(side=tk.LEFT, padx=(12, 8))
        ttk.Label(ed, text="HP < % (0=any)", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(ed, textvariable=self._sim_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(ed, text="Only in combat", variable=self._sim_combat, style=theme.S_CHECK).pack(
            side=tk.LEFT, padx=(10, 0))

        ed2 = ttk.Frame(rot, style=theme.S_FRAME)
        ed2.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(ed2, text="Add", command=self._sim_add_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(ed2, text="Update", command=self._sim_update_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(ed2, text="Remove", command=self._sim_remove_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(ed2, text="Up", command=lambda: self._sim_move(-1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(ed2, text="Down", command=lambda: self._sim_move(1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)

        ak = ttk.LabelFrame(root, text="After kill (sit to regen)", style=theme.S_LF)
        ak.pack(fill=tk.X, padx=10, pady=(0, 8))
        rc1 = ttk.Frame(ak, style=theme.S_FRAME)
        rc1.pack(fill=tk.X, padx=8, pady=8)
        ttk.Checkbutton(
            rc1, text="Sit after kill if HP below %", variable=self._v_post_kill_en, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        ttk.Entry(rc1, textvariable=self._v_post_kill_sit_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc1, text="stand at HP ≥ %", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(rc1, textvariable=self._v_post_kill_stand_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        loot = ttk.LabelFrame(root, text="Loot", style=theme.S_LF)
        loot.pack(fill=tk.X, padx=10, pady=(0, 8))
        lf = ttk.Frame(loot, style=theme.S_FRAME)
        lf.pack(fill=tk.X, padx=8, pady=8)
        ttk.Checkbutton(lf, text="Auto loot", variable=self._v_auto_loot, style=theme.S_CHECK).pack(side=tk.LEFT)
        ttk.Label(lf, text="range", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(lf, textvariable=self._v_loot_range, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT)

        act = ttk.Frame(root, style=theme.S_FRAME)
        act.pack(fill=tk.X, padx=14, pady=(0, 6))
        self._btn_save = ttk.Button(act, text="Save to file", command=self._save_file, style=theme.S_BTN_PRIMARY)
        self._btn_save.pack(side=tk.LEFT, padx=2)
        ttk.Button(act, text="Reload from file", command=self._reload_file, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(act, text="Preset: farm", command=self._preset_farm_anchor, style=theme.S_BTN).pack(side=tk.LEFT, padx=(12, 2))

        self._adv_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            root, text="Show advanced", variable=self._adv_show, command=self._toggle_adv_combat, style=theme.S_CHECK,
        ).pack(anchor="w", padx=14, pady=(4, 2))
        self._adv_combat_frame = ttk.Frame(root, style=theme.S_FRAME)

        self._sim_refresh_pick_combo()

    def _sim_row_name(self, r: CombatRule) -> str:
        if r.kind == "skill":
            return gre.resolve_skill_name(r.skill_id) or "—"
        return gre.resolve_item_name(r.item_id) or "—"

    def _sim_inventory_combo_values(self) -> list[str]:
        """Template id + name + qty + object id from live ItemList (same as inventory in game)."""
        be = getattr(self.bot, "bot_engine", None)
        if not be or not be.world.inventory_by_object:
            return []
        out: list[str] = []
        for oid, (tid, cnt) in sorted(be.world.inventory_by_object.items()):
            nm = gre.resolve_item_name(tid) or "?"
            out.append(f"{tid} — {nm}  ×{cnt}  (0x{oid:X})")
        return out

    def _refresh_sim_tree(self) -> None:
        self._sim_tree.delete(*self._sim_tree.get_children())
        for i, r in enumerate(self._profile.rules):
            self._sim_tree.insert(
                "", tk.END, iid=str(i),
                values=(
                    str(i + 1),
                    r.kind,
                    self._sim_row_name(r)[:40],
                    combat_when_summary(r),
                    self._learned_label(r),
                ),
            )

    def _sim_refresh_pick_combo(self) -> None:
        if self._sim_kind.get() == "skill":
            vals: list[str] = []
            be = getattr(self.bot, "bot_engine", None)
            if be and be.world.my_skills:
                for sid in sorted(be.world.my_skills.keys()):
                    nm = gre.resolve_skill_name(sid) or "?"
                    vals.append(f"{sid} — {nm}")
            else:
                for sid, nm in gre.search_skills("", 80):
                    vals.append(f"{sid} — {nm}")
            self._sim_pick_combo.configure(values=vals)
            if vals:
                self._sim_pick_var.set(vals[0])
        else:
            vals = self._sim_inventory_combo_values()
            self._sim_pick_combo.configure(values=vals)
            if vals:
                self._sim_pick_var.set(vals[0])
            else:
                self._sim_pick_var.set("")

    def _parse_sim_pick_id(self) -> int | None:
        line = (self._sim_pick_var.get() or "").strip()
        if not line:
            return None
        if self._sim_kind.get() == "skill":
            head = line.split("—", 1)[0].strip() if "—" in line else line.split()[0]
        else:
            if "—" in line:
                head = line.split("—", 1)[0].strip()
            else:
                head = line.split(":", 1)[0].strip()
        try:
            return int(head, 10)
        except ValueError:
            try:
                return int(head, 16)
            except ValueError:
                return None

    def _sync_sim_form_from_selection(self) -> None:
        sel = self._sim_tree.selection()
        if not sel:
            return
        r = self._profile.rules[int(sel[0])]
        self._sim_kind.set(r.kind)
        self._sim_refresh_pick_combo()
        if r.kind == "skill":
            self._sim_pick_var.set(
                next(
                    (x for x in self._sim_pick_combo.cget("values") if x.split("—", 1)[0].strip() == str(r.skill_id)),
                    f"{r.skill_id} — {gre.resolve_skill_name(r.skill_id) or '?'}",
                )
            )
        else:
            vals = self._sim_pick_combo.cget("values")
            match = next(
                (
                    x
                    for x in vals
                    if x.split("—", 1)[0].strip() == str(r.item_id)
                ),
                None,
            )
            self._sim_pick_var.set(
                match or f"{r.item_id} — {gre.resolve_item_name(r.item_id) or '?'}",
            )
        self._sim_hp.set(str(r.hp_below_pct) if r.hp_below_pct else "0")
        self._sim_combat.set(r.only_in_combat)

    def _parse_sim_rule(self) -> CombatRule | None:
        rid = self._parse_sim_pick_id()
        if rid is None or rid <= 0:
            if self._sim_kind.get() == "item" and not self._sim_inventory_combo_values():
                messagebox.showerror(
                    "Auto combat",
                    "Inventory is empty in the bot. Open your inventory in game once (ItemList).",
                )
            else:
                messagebox.showerror("Auto combat", "Pick a skill or item from the list.")
            return None
        try:
            hp = float(self._sim_hp.get() or 0)
        except ValueError:
            messagebox.showerror("Auto combat", "Invalid HP %.")
            return None
        if self._sim_kind.get() == "skill":
            return CombatRule(
                kind="skill", skill_id=rid, item_id=0,
                hp_below_pct=hp, mp_below_pct=0.0, hp_min_pct=0.0, mp_min_pct=0.0,
                only_in_combat=self._sim_combat.get(), cooldown_sec=0.0, rebuff_missing_skill_id=0,
                require_target_missing_abnormal_ids=[], require_target_has_abnormal_ids=[],
                fire_before_first_attack=False,
            )
        return CombatRule(
            kind="item", skill_id=0, item_id=rid,
            hp_below_pct=hp, mp_below_pct=0.0, hp_min_pct=0.0, mp_min_pct=0.0,
            only_in_combat=self._sim_combat.get(), cooldown_sec=0.0, rebuff_missing_skill_id=0,
            require_target_missing_abnormal_ids=[], require_target_has_abnormal_ids=[],
            fire_before_first_attack=False,
        )

    def _sim_add_rule(self) -> None:
        if not self._apply_globals_to_profile():
            return
        r = self._parse_sim_rule()
        if r is None:
            return
        self._profile.rules.append(r)
        self._push_profile()

    def _sim_update_rule(self) -> None:
        sel = self._sim_tree.selection()
        if not sel:
            messagebox.showinfo("Auto combat", "Select a row first.")
            return
        if not self._apply_globals_to_profile():
            return
        r = self._parse_sim_rule()
        if r is None:
            return
        idx = int(sel[0])
        old = self._profile.rules[idx]
        r.hp_min_pct = old.hp_min_pct
        r.mp_below_pct = old.mp_below_pct
        r.mp_min_pct = old.mp_min_pct
        r.cooldown_sec = old.cooldown_sec
        r.rebuff_missing_skill_id = old.rebuff_missing_skill_id
        r.require_target_missing_abnormal_ids = list(old.require_target_missing_abnormal_ids)
        r.require_target_has_abnormal_ids = list(old.require_target_has_abnormal_ids)
        r.fire_before_first_attack = old.fire_before_first_attack
        self._profile.rules[idx] = r
        self._push_profile()

    def _sim_remove_rule(self) -> None:
        sel = self._sim_tree.selection()
        if not sel:
            return
        del self._profile.rules[int(sel[0])]
        self._push_profile()

    def _sim_move(self, delta: int) -> None:
        sel = self._sim_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        j = idx + delta
        if j < 0 or j >= len(self._profile.rules):
            return
        self._profile.rules[idx], self._profile.rules[j] = (
            self._profile.rules[j], self._profile.rules[idx])
        self._push_profile()
        self._sim_tree.selection_set(str(j))

    def _build(self) -> None:
        self._ensure_combat_vars()
        root = self._scroll.content
        self._build_simple_top(root)
        f = self._adv_combat_frame

        rec = ttk.LabelFrame(f, text="Recovery (sit / HP / MP)", style=theme.S_LF)
        rec.pack(fill=tk.X, padx=10, pady=(0, 6))
        rc0 = ttk.Frame(rec, style=theme.S_FRAME)
        rc0.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(rc0, text="In combat: sit if HP below %", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(rc0, textvariable=self._v_combat_sit_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc0, text="stand when HP ≥ %", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(rc0, textvariable=self._v_combat_stand_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            rc0,
            text="(ignored while you have a target — use post-kill sit or items)",
            style=theme.S_HELP,
            wraplength=400,
        ).pack(side=tk.LEFT, padx=(12, 0))

        rc1 = ttk.Frame(rec, style=theme.S_FRAME)
        rc1.pack(fill=tk.X, padx=8, pady=2)
        ttk.Checkbutton(
            rc1, text="After kill: sit to regen if HP below %", variable=self._v_post_kill_en, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        ttk.Entry(rc1, textvariable=self._v_post_kill_sit_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc1, text="stand when HP ≥ %", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(rc1, textvariable=self._v_post_kill_stand_hp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        rc2 = ttk.Frame(rec, style=theme.S_FRAME)
        rc2.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(
            rc2,
            text="Optional MP while sitting: set both fields > 0 to also wait until MP ≥ target before standing (HP target still required).",
            style=theme.S_HELP, wraplength=820,
        ).pack(anchor="w")
        rc2b = ttk.Frame(rec, style=theme.S_FRAME)
        rc2b.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(rc2b, text="MP gate: first field & second both > 0 enables. Target MP ≥ %", style=theme.S_LABEL).pack(
            side=tk.LEFT)
        ttk.Entry(rc2b, textvariable=self._v_rec_sit_mp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Entry(rc2b, textvariable=self._v_rec_stand_mp, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(rc2b, text="Max sit wait (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Entry(rc2b, textvariable=self._v_rec_max_wait, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        loot_fr = ttk.Frame(rec, style=theme.S_FRAME)
        loot_fr.pack(fill=tk.X, padx=8, pady=(2, 4))
        ttk.Checkbutton(loot_fr, text="Auto loot", variable=self._v_auto_loot, style=theme.S_CHECK).pack(side=tk.LEFT)
        ttk.Label(loot_fr, text="pickup range", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(loot_fr, textvariable=self._v_loot_range, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=(0, 4))

        pkt_fr = ttk.Frame(rec, style=theme.S_FRAME)
        pkt_fr.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(pkt_fr, text="After kill: drop target (0x37) payload", style=theme.S_LABEL).pack(side=tk.LEFT)
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
            text="h = 2-byte zero · d = 4-byte zero",
            style=theme.S_HELP,
        ).pack(side=tk.LEFT, padx=(4, 0))

        sk_fr = ttk.Frame(rec, style=theme.S_FRAME)
        sk_fr.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(sk_fr, text="Combat skill packet (auto rules / sweep)", style=theme.S_LABEL).pack(
            side=tk.LEFT
        )
        ttk.Combobox(
            sk_fr,
            textvariable=self._v_combat_skill_pkt,
            width=5,
            values=("39", "2f"),
            state="readonly",
            style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(
            sk_fr,
            text="39 = RequestMagicSkillUse · 2f = shortcut bar (Teon)",
            style=theme.S_HELP,
        ).pack(side=tk.LEFT, padx=(4, 0))

        sk_pay_fr = ttk.Frame(rec, style=theme.S_FRAME)
        sk_pay_fr.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(sk_pay_fr, text="0x39 skill body (only if packet=39)", style=theme.S_LABEL).pack(
            side=tk.LEFT
        )
        ttk.Combobox(
            sk_pay_fr,
            textvariable=self._v_magic_skill_payload,
            width=5,
            values=("dcb", "ddd", "dcc"),
            state="readonly",
            style=theme.S_ENTRY,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(
            sk_pay_fr,
            text="Must match Buffs tab (often ddd on Teon/L2J — wrong value can disconnect on Spoil/Sweep)",
            style=theme.S_HELP,
            wraplength=520,
        ).pack(side=tk.LEFT, padx=(4, 0))

        sit_sf = ttk.LabelFrame(f, text="Post-kill recovery sit — safety", style=theme.S_LF)
        sit_sf.pack(fill=tk.X, padx=10, pady=(0, 6))
        ss0 = ttk.Frame(sit_sf, style=theme.S_FRAME)
        ss0.pack(fill=tk.X, padx=8, pady=(6, 2))
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
        ttk.Entry(ss1, textvariable=self._v_dmg_gate, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ss2 = ttk.Frame(sit_sf, style=theme.S_FRAME)
        ss2.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(
            ss2,
            text="SC_ChangeWaitType «sitting» dword (0=Acis/Teon usual, 1=invert if sit/stand is wrong)",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        ttk.Entry(ss2, textvariable=self._v_cwt_sit_raw, width=3, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(ss2, text="Stand toggles after regen (1–4)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Entry(ss2, textvariable=self._v_rec_stand_toggles, width=3, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        tim = ttk.LabelFrame(f, text="Timing (auto-combat loop)", style=theme.S_LF)
        tim.pack(fill=tk.X, padx=10, pady=(0, 6))

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

        tgt = ttk.LabelFrame(f, text="Targeting (advanced)", style=theme.S_LF)
        tgt.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Label(
            tgt,
            text="Aggro uses recent hits (SC_Attack). Blacklist / whitelist = template npcId. Party / never-attack = objectId.",
            style=theme.S_HELP,
            wraplength=820,
        ).pack(anchor="w", padx=8, pady=(4, 2))
        tr = ttk.Frame(tgt, style=theme.S_FRAME)
        tr.pack(fill=tk.X, padx=8, pady=2)
        ttk.Checkbutton(
            tr, text="Prefer mobs that recently hit me", variable=self._v_prefer_aggro, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        ttk.Label(tr, text="Keep target within", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(tr, textvariable=self._v_retain_dist, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(tr, text="(0 = re-pick every tick)", style=theme.S_HELP).pack(side=tk.LEFT)

        tr2 = ttk.Frame(tgt, style=theme.S_FRAME)
        tr2.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(tr2, text="NPC blacklist ids", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(tr2, textvariable=self._v_npc_blacklist, width=42, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(tr2, text="Example ids", command=self._targeting_example_blacklist, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=4)

        tr3 = ttk.Frame(tgt, style=theme.S_FRAME)
        tr3.pack(fill=tk.X, padx=8, pady=2)
        ttk.Checkbutton(
            tr3, text="Only whitelist NPCs", variable=self._v_whitelist_only, style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        ttk.Label(tr3, text="Whitelist ids", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(tr3, textvariable=self._v_npc_whitelist, width=38, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4)

        tr4 = ttk.Frame(tgt, style=theme.S_FRAME)
        tr4.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(
            tr4,
            text="Max |ΔZ| same floor (0 = any Z / other floors)",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        ttk.Entry(tr4, textvariable=self._v_zrange, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            tr4,
            text="Skip summoned NPCs (off unless you need it — wrong flag hides all mobs on some shards)",
            variable=self._v_skip_summon,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=10)
        ttk.Label(tr4, text="Min gap between combat skills (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(tr4, textvariable=self._v_skill_gap, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        tr5 = ttk.Frame(tgt, style=theme.S_FRAME)
        tr5.pack(fill=tk.X, padx=8, pady=(2, 6))
        ttk.Label(tr5, text="Never attack OIDs", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(tr5, textvariable=self._v_never_oid, width=26, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(tr5, text="Party protect OIDs", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Entry(tr5, textvariable=self._v_party_oid, width=26, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        anc = ttk.LabelFrame(f, text="Combat anchor, sweep, rotation tick", style=theme.S_LF)
        anc.pack(fill=tk.X, padx=10, pady=(0, 6))
        ttk.Label(
            anc,
            text="Anchor = your position when auto-combat starts. Leash ignores mobs and drops outside the radius. Idle reset > 0 recenters after no mobs.",
            style=theme.S_HELP,
            wraplength=820,
        ).pack(anchor="w", padx=8, pady=(4, 2))
        ar = ttk.Frame(anc, style=theme.S_FRAME)
        ar.pack(fill=tk.X, padx=8, pady=2)
        ttk.Checkbutton(ar, text="Anchor leash", variable=self._v_anchor_en, style=theme.S_CHECK).pack(
            side=tk.LEFT)
        ttk.Label(ar, text="Radius", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(ar, textvariable=self._v_anchor_r, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(ar, text="Idle reset (s, 0=off)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(ar, textvariable=self._v_anchor_idle, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            ar, text="Loot obeys anchor", variable=self._v_loot_anchor, style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=10)
        ar2 = ttk.Frame(anc, style=theme.S_FRAME)
        ar2.pack(fill=tk.X, padx=8, pady=2)
        ttk.Checkbutton(
            ar2, text="Retarget to mob hitting you (mid-fight)", variable=self._v_retarget_aggro,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT)
        ttk.Label(ar2, text="Aggro window s", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(ar2, textvariable=self._v_aggro_win, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(ar2, text="Rule tick in kill-loop (s, 0=off)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(ar2, textvariable=self._v_rules_tick, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ar3 = ttk.Frame(anc, style=theme.S_FRAME)
        ar3.pack(fill=tk.X, padx=8, pady=(2, 6))
        ttk.Checkbutton(ar3, text="Post-kill Sweep skill", variable=self._v_sweep_en, style=theme.S_CHECK).pack(
            side=tk.LEFT)
        ttk.Label(ar3, text="skill id", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(ar3, textvariable=self._v_sweep_sid, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(ar3, text="delay s", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(ar3, textvariable=self._v_sweep_dly, width=5, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            ar3,
            text="Sit while idle (no mobs) using HP thresholds below — not under attack",
            variable=self._v_idle_sit_en,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=12)

        live = ttk.LabelFrame(f, text="Live from game (updates every ~2s)", style=theme.S_LF)
        live.pack(fill=tk.X, padx=10, pady=(0, 6))
        live_row = ttk.Frame(live, style=theme.S_FRAME)
        live_row.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        lf_sk = ttk.LabelFrame(live_row, text="SkillList → my_skills", style=theme.S_LF)
        lf_sk.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self._live_skills = tk.Listbox(
            lf_sk, height=6, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        sb_ls = ttk.Scrollbar(lf_sk, orient=tk.VERTICAL, command=self._live_skills.yview)
        self._live_skills.config(yscrollcommand=sb_ls.set)
        self._live_skills.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_ls.pack(side=tk.RIGHT, fill=tk.Y)
        lf_inv = ttk.LabelFrame(live_row, text="ItemList → inventory (open inv once)", style=theme.S_LF)
        lf_inv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._live_inv = tk.Listbox(
            lf_inv, height=6, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
            font=theme.FONT_MONO, exportselection=False,
        )
        sb_li = ttk.Scrollbar(lf_inv, orient=tk.VERTICAL, command=self._live_inv.yview)
        self._live_inv.config(yscrollcommand=sb_li.set)
        self._live_inv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_li.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(f, textvariable=self._learned_var, style=theme.S_HELP, font=theme.FONT_MONO).pack(
            anchor="w", padx=14, pady=(0, 4))

        rot = ttk.LabelFrame(f, text="Skill rotation", style=theme.S_LF)
        rot.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        tree_fr = ttk.Frame(rot, style=theme.S_FRAME)
        tree_fr.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 2))
        cols = (
            "#", "Type", "ID", "Name", "Learned",
            "HP<%", "MP<%", "HP≥%", "MP≥%", "In fight", "B4 1st", "CD s", "Rebuff",
            "Mob lacks abn", "Mob has abn",
        )
        self._tree = ttk.Treeview(tree_fr, columns=cols, show="headings", height=11, style=theme.S_TREE)
        widths = {
            "#": 36, "Type": 56, "ID": 60, "Name": 160, "Learned": 52,
            "HP<%": 48, "MP<%": 48, "HP≥%": 48, "MP≥%": 48,
            "In fight": 54, "B4 1st": 44, "CD s": 44, "Rebuff": 56,
            "Mob lacks abn": 88, "Mob has abn": 88,
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
        ttk.Label(
            form,
            text="Select a table row to edit, or fill the form and click Add rule.",
            style=theme.S_HELP,
        ).pack(anchor="w", padx=10, pady=(6, 0))

        r0 = ttk.Frame(form, style=theme.S_FRAME)
        r0.pack(fill=tk.X, padx=8, pady=4)
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
        self._search.trace_add("write", lambda *_: self._refresh_pick_list())
        ttk.Entry(r1, textvariable=self._search, width=22, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            r1,
            text="Only skills from SkillList",
            variable=self._only_learned_pick,
            command=self._refresh_pick_list,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(r1, text="Numeric ID:", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        self._rid.trace_add("write", lambda *_: self._update_id_hint())
        ttk.Entry(r1, textvariable=self._rid, width=10, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r1, textvariable=self._id_hint, style=theme.S_HELP).pack(side=tk.LEFT, padx=6)

        lb_fr = ttk.Frame(form, style=theme.S_FRAME)
        lb_fr.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._pick = tk.Listbox(
            lb_fr, height=6, bg=theme.COL_LOG_BG, fg=theme.COL_TEXT,
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
        ttk.Entry(r2, textvariable=self._hp, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r2, text="MP below %:", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(r2, textvariable=self._mp, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(r2, text="Only in combat", variable=self._only_combat, style=theme.S_CHECK).pack(side=tk.LEFT, padx=14)
        ttk.Checkbutton(
            r2,
            text="Before 1st hit (new target)",
            variable=self._fire_before_first,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(r2, text="Cooldown s:", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(r2, textvariable=self._cd, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        r2m = ttk.Frame(form, style=theme.S_FRAME)
        r2m.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(
            r2m,
            text="HP min % (0=off, need HP≥ for rule — e.g. don’t nuke while critical):",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        ttk.Entry(r2m, textvariable=self._hp_min, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r2m, text="MP min % (0=off — e.g. Mortal Blow only if mana ≥):", style=theme.S_LABEL).pack(
            side=tk.LEFT, padx=(10, 0))
        ttk.Entry(r2m, textvariable=self._mp_min, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        r2b = ttk.Frame(form, style=theme.S_FRAME)
        r2b.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(
            r2b,
            text="Rebuff: fire only if buff skill id is missing (0 = off):",
            style=theme.S_LABEL,
        ).pack(side=tk.LEFT)
        ttk.Entry(r2b, textvariable=self._rebuff, width=8, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(
            r2b,
            text="(id from AbnormalStatusUpdate)",
            style=theme.S_HELP,
        ).pack(side=tk.LEFT, padx=4)

        r2t = ttk.Frame(form, style=theme.S_FRAME)
        r2t.pack(fill=tk.X, padx=8, pady=(0, 4))
        ttk.Label(
            r2t,
            text="Target abnormal (comma ids — spoil if server sends NPC buff list): "
            "fire only if current mob missing ALL of:",
            style=theme.S_LABEL,
            wraplength=680,
        ).pack(anchor="w")
        r2t2 = ttk.Frame(form, style=theme.S_FRAME)
        r2t2.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Entry(r2t2, textvariable=self._tgt_miss_abn, width=50, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=(0, 8))
        ttk.Label(r2t2, text="…and has ANY of (0=ignore):", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(r2t2, textvariable=self._tgt_has_abn, width=28, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4)

        r3 = ttk.Frame(form, style=theme.S_FRAME)
        r3.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(r3, text="Delays: after target (s)", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(r3, textvariable=self._d_target, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Label(r3, text="after skill (s)", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Entry(r3, textvariable=self._d_skill, width=6, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)

        ttk.Label(f, text="Actions", style=theme.S_SECTION).pack(anchor="w", padx=14, pady=(10, 2))
        r4 = ttk.Frame(f, style=theme.S_FRAME)
        r4.pack(fill=tk.X, padx=14, pady=(0, 4))
        ttk.Label(r4, text="Rules:", style=theme.S_LABEL).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(r4, text="Add rule", command=self._add_rule, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r4, text="Update selected", command=self._update_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r4, text="Remove", command=self._remove_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r4, text="Duplicate", command=self._duplicate_selected, style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r4, text="Move up", command=lambda: self._move(-1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)
        ttk.Button(r4, text="Move down", command=lambda: self._move(1), style=theme.S_BTN).pack(side=tk.LEFT, padx=2)

        self._on_kind_change()
        self._push_profile()
        self._tick_learned()

    def _tick_learned(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        n = len(be.world.my_skills) if be else 0
        self._learned_var.set(f"Learned skills (SkillList): {n}")
        self._sim_refresh_pick_combo()
        self._refresh_learned_column()
        self._refresh_live_lists(be)
        gp = getattr(self.bot, "game_proxy", None)
        sess = gp.session if gp else None
        st = tk.NORMAL if (sess and sess.crypto_initialized) else tk.DISABLED
        if hasattr(self, "_btn_save"):
            self._btn_save.config(state=st)
        self._scroll.after(2000, self._tick_learned)

    @staticmethod
    def _parse_csv_ints(raw: str) -> list[int]:
        out: list[int] = []
        for part in raw.replace(",", " ").split():
            try:
                v = int(part.strip(), 0)
                if v != 0:
                    out.append(v)
            except ValueError:
                continue
        return out

    def _targeting_example_blacklist(self) -> None:
        self._v_npc_blacklist.set("20001, 20002")

    def _preset_farm_anchor(self) -> None:
        if not messagebox.askyesno(
            "Auto combat",
            "Apply preset? Enables anchor leash (1500), loot obeys anchor, retarget to aggro, "
            "rule tick 0.45s. Does not remove existing rules.",
        ):
            return
        self._profile.combat_anchor_leash_enabled = True
        self._profile.combat_anchor_leash_radius = 1500.0
        self._profile.loot_respect_anchor_leash = True
        self._profile.retarget_to_aggro_enabled = True
        self._profile.combat_rules_tick_sec = 0.45
        self._v_anchor_en.set(True)
        self._v_anchor_r.set("1500")
        self._v_loot_anchor.set(True)
        self._v_retarget_aggro.set(True)
        self._v_rules_tick.set("0.45")
        self._push_profile()

    def flush_profile_to_engine(self) -> bool:
        """Apply form fields to in-memory profile and push to BotEngine (no disk write)."""
        if not self._apply_globals_to_profile():
            return False
        cb = getattr(self.bot, "apply_combat_profile", None)
        if cb:
            cb(self._profile)
        return True

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
        def _abn_s(xs: list[int]) -> str:
            if not xs:
                return "—"
            s = ",".join(str(x) for x in xs[:3])
            return s + ("…" if len(xs) > 3 else "")

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
            "yes" if r.fire_before_first_attack else "—",
            f"{r.cooldown_sec:g}" if r.cooldown_sec else "—",
            str(r.rebuff_missing_skill_id) if r.rebuff_missing_skill_id else "—",
            _abn_s(r.require_target_missing_abnormal_ids),
            _abn_s(r.require_target_has_abnormal_ids),
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
            if hasattr(self, "_sim_tree") and self._sim_tree.exists(iid):
                self._sim_tree.set(iid, "Lrn", self._learned_label(r))

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
        self._fire_before_first.set(r.fire_before_first_attack)
        self._cd.set(str(r.cooldown_sec) if r.cooldown_sec else "0")
        self._rebuff.set(str(r.rebuff_missing_skill_id) if r.rebuff_missing_skill_id else "0")
        self._tgt_miss_abn.set(", ".join(str(x) for x in r.require_target_missing_abnormal_ids))
        self._tgt_has_abn.set(", ".join(str(x) for x in r.require_target_has_abnormal_ids))
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
        miss_abn = self._parse_csv_ints(self._tgt_miss_abn.get())
        has_abn = self._parse_csv_ints(self._tgt_has_abn.get())
        k = self._kind.get()
        if k == "skill":
            return CombatRule(
                kind="skill", skill_id=rid, item_id=0,
                hp_below_pct=hp, mp_below_pct=mp,
                hp_min_pct=hp_min, mp_min_pct=mp_min,
                only_in_combat=self._only_combat.get(), cooldown_sec=cd,
                rebuff_missing_skill_id=rebuff,
                require_target_missing_abnormal_ids=miss_abn,
                require_target_has_abnormal_ids=has_abn,
                fire_before_first_attack=self._fire_before_first.get(),
            )
        return CombatRule(
            kind="item", skill_id=0, item_id=rid,
            hp_below_pct=hp, mp_below_pct=mp,
            hp_min_pct=hp_min, mp_min_pct=mp_min,
            only_in_combat=self._only_combat.get(), cooldown_sec=cd,
            rebuff_missing_skill_id=rebuff,
            require_target_missing_abnormal_ids=miss_abn,
            require_target_has_abnormal_ids=has_abn,
            fire_before_first_attack=self._fire_before_first.get(),
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
            self._profile.combat_skill_packet = normalize_buff_skill_packet(self._v_combat_skill_pkt.get())
            self._v_combat_skill_pkt.set(self._profile.combat_skill_packet)
            self._profile.magic_skill_payload = normalize_magic_skill_payload(self._v_magic_skill_payload.get())
            self._v_magic_skill_payload.set(self._profile.magic_skill_payload)
            self._profile.never_sit_while_target = self._v_never_sit_tgt.get()
            self._profile.incoming_damage_sit_block_sec = float(self._v_dmg_gate.get())
            raw_cwt = int(float(self._v_cwt_sit_raw.get()))
            self._profile.recovery_change_wait_type_sit_raw = max(0, min(1, raw_cwt))
            rst = int(float(self._v_rec_stand_toggles.get()))
            self._profile.recovery_stand_toggle_attempts = max(1, min(4, rst))
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
            self._profile.prefer_aggro_mobs = self._v_prefer_aggro.get()
            self._profile.retain_current_target_max_dist = float(self._v_retain_dist.get())
            self._profile.npc_blacklist_ids = self._parse_csv_ints(self._v_npc_blacklist.get())
            self._profile.npc_whitelist_ids = self._parse_csv_ints(self._v_npc_whitelist.get())
            self._profile.attack_only_whitelist_mobs = self._v_whitelist_only.get()
            self._profile.target_z_range_max = float(self._v_zrange.get())
            self._profile.skip_summoned_npcs = self._v_skip_summon.get()
            self._profile.never_attack_object_ids = self._parse_csv_ints(self._v_never_oid.get())
            self._profile.party_protect_object_ids = self._parse_csv_ints(self._v_party_oid.get())
            self._profile.combat_skill_min_interval_sec = float(self._v_skill_gap.get())
            self._profile.combat_rules_tick_sec = float(self._v_rules_tick.get())
            self._profile.post_kill_sweep_enabled = self._v_sweep_en.get()
            self._profile.post_kill_sweep_skill_id = int(float(self._v_sweep_sid.get().strip() or 0))
            self._profile.post_kill_sweep_delay_sec = float(self._v_sweep_dly.get())
            self._profile.combat_anchor_leash_enabled = self._v_anchor_en.get()
            self._profile.combat_anchor_leash_radius = float(self._v_anchor_r.get())
            self._profile.combat_anchor_reset_idle_sec = float(self._v_anchor_idle.get())
            self._profile.retarget_to_aggro_enabled = self._v_retarget_aggro.get()
            self._profile.aggro_retarget_window_sec = float(self._v_aggro_win.get())
            self._profile.combat_sit_while_idle_enabled = self._v_idle_sit_en.get()
            self._profile.loot_respect_anchor_leash = self._v_loot_anchor.get()
        except ValueError:
            messagebox.showerror(
                "Auto combat",
                "Invalid number in delays, recovery, loot, timing, or targeting fields.",
            )
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

    def _duplicate_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Auto combat", "Select a rule row first.")
            return
        idx = int(sel[0])
        r = self._profile.rules[idx]
        self._profile.rules.insert(
            idx + 1,
            replace(
                r,
                require_target_missing_abnormal_ids=list(r.require_target_missing_abnormal_ids),
                require_target_has_abnormal_ids=list(r.require_target_has_abnormal_ids),
            ),
        )
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
        p = resolve_combat_profile_write_path(character_name=cn)
        self._path_hint.configure(text=f"Save: {p.name}")

    def _save_file(self) -> None:
        if not self._apply_globals_to_profile():
            return
        cn = self._character_name_for_config()
        try:
            save_profile(self._profile, character_name=cn)
        except (OSError, TypeError, ValueError) as exc:
            _log.error("Combat profile save failed: %s", exc)
            messagebox.showerror("Auto combat", f"Save failed: {exc}")
            return
        self._update_path_hint()
        messagebox.showinfo("Auto combat", f"Saved {len(self._profile.rules)} rules.")

    def _reload_file(self) -> None:
        self._profile = self._load_profile_for_ui()
        self._update_path_hint()
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
        self._v_combat_skill_pkt.set(normalize_buff_skill_packet(self._profile.combat_skill_packet))
        self._v_magic_skill_payload.set(normalize_magic_skill_payload(self._profile.magic_skill_payload))
        self._v_never_sit_tgt.set(self._profile.never_sit_while_target)
        self._v_dmg_gate.set(str(self._profile.incoming_damage_sit_block_sec))
        self._v_cwt_sit_raw.set(str(self._profile.recovery_change_wait_type_sit_raw))
        self._v_rec_stand_toggles.set(str(self._profile.recovery_stand_toggle_attempts))
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
        self._v_prefer_aggro.set(self._profile.prefer_aggro_mobs)
        self._v_retain_dist.set(str(self._profile.retain_current_target_max_dist))
        self._v_npc_blacklist.set(", ".join(str(x) for x in self._profile.npc_blacklist_ids))
        self._v_npc_whitelist.set(", ".join(str(x) for x in self._profile.npc_whitelist_ids))
        self._v_whitelist_only.set(self._profile.attack_only_whitelist_mobs)
        self._v_zrange.set(str(self._profile.target_z_range_max))
        self._v_skip_summon.set(self._profile.skip_summoned_npcs)
        self._v_never_oid.set(", ".join(str(x) for x in self._profile.never_attack_object_ids))
        self._v_party_oid.set(", ".join(str(x) for x in self._profile.party_protect_object_ids))
        self._v_skill_gap.set(str(self._profile.combat_skill_min_interval_sec))
        self._v_rules_tick.set(str(self._profile.combat_rules_tick_sec))
        self._v_sweep_en.set(self._profile.post_kill_sweep_enabled)
        self._v_sweep_sid.set(str(self._profile.post_kill_sweep_skill_id))
        self._v_sweep_dly.set(str(self._profile.post_kill_sweep_delay_sec))
        self._v_anchor_en.set(self._profile.combat_anchor_leash_enabled)
        self._v_anchor_r.set(str(self._profile.combat_anchor_leash_radius))
        self._v_anchor_idle.set(str(self._profile.combat_anchor_reset_idle_sec))
        self._v_retarget_aggro.set(self._profile.retarget_to_aggro_enabled)
        self._v_aggro_win.set(str(self._profile.aggro_retarget_window_sec))
        self._v_idle_sit_en.set(self._profile.combat_sit_while_idle_enabled)
        self._v_loot_anchor.set(self._profile.loot_respect_anchor_leash)
        self._push_profile()

    def _push_profile(self) -> None:
        self._refresh_tree()
        self._refresh_sim_tree()
        cb = getattr(self.bot, "apply_combat_profile", None)
        if cb:
            cb(self._profile)
