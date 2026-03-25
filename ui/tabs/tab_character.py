"""Character tab — HP/MP display + combat controls."""
import tkinter as tk
from tkinter import ttk

from ui import theme


class CharacterTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._combat_running = False
        self.frame = ttk.Frame(parent, style=theme.S_FRAME)
        self._build()
        self._update()

    def _build(self) -> None:
        f = self.frame

        ttk.Label(f, text="Character", style=theme.S_TITLE).pack(pady=(10, 6), padx=12, anchor="w")

        grid = ttk.Frame(f, style=theme.S_FRAME)
        grid.pack(fill=tk.X, padx=16, pady=4)

        self._vars = {}
        for row, (label, key) in enumerate([
            ("Name", "name"),
            ("Level", "level"),
            ("HP", "hp"),
            ("MP", "mp"),
            ("CP", "cp"),
            ("Pos", "pos"),
            ("Auto state", "state"),
        ]):
            ttk.Label(grid, text=label + ":", style=theme.S_LABEL, width=8, anchor="e").grid(
                row=row, column=0, sticky="e", pady=2, padx=(0, 8))
            var = tk.StringVar(value="—")
            self._vars[key] = var
            ttk.Label(grid, textvariable=var, anchor="w", style=theme.S_LABEL, font=theme.FONT_MONO).grid(
                row=row, column=1, sticky="w")

        bar_frame = ttk.Frame(f, style=theme.S_FRAME)
        bar_frame.pack(fill=tk.X, padx=16, pady=(8, 4))

        ttk.Label(bar_frame, text="HP", style=theme.S_LABEL, width=4, anchor="e").grid(row=0, column=0)
        self._hp_bar = ttk.Progressbar(bar_frame, length=360, maximum=100, style=theme.S_PROG)
        self._hp_bar.grid(row=0, column=1, padx=8, pady=2)

        ttk.Label(bar_frame, text="MP", style=theme.S_LABEL, width=4, anchor="e").grid(row=1, column=0)
        self._mp_bar = ttk.Progressbar(bar_frame, length=360, maximum=100, style=theme.S_PROG)
        self._mp_bar.grid(row=1, column=1, padx=8, pady=2)

        party_lf = ttk.LabelFrame(f, text="Party (HP / MP / CP + buff count from PartySpelled)", style=theme.S_LF)
        party_lf.pack(fill=tk.BOTH, expand=True, padx=12, pady=(10, 6))
        self._party_hint = tk.StringVar(
            value="Not in party or waiting for PartySmallWindowAll from server…",
        )
        ttk.Label(party_lf, textvariable=self._party_hint, style=theme.S_LABEL_MUTED, wraplength=700).pack(
            anchor="w", padx=8, pady=(6, 2))
        pt = ttk.Frame(party_lf, style=theme.S_FRAME)
        pt.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 6))
        cols = ("hp", "mp", "cp", "buffs")
        self._party_tree = ttk.Treeview(
            pt,
            columns=cols,
            show="tree headings",
            height=6,
            style=theme.S_TREE,
        )
        self._party_tree.heading("#0", text="Name (Lv)")
        self._party_tree.column("#0", width=160, stretch=True)
        self._party_tree.heading("hp", text="HP")
        self._party_tree.column("hp", width=120, stretch=False)
        self._party_tree.heading("mp", text="MP")
        self._party_tree.column("mp", width=120, stretch=False)
        self._party_tree.heading("cp", text="CP")
        self._party_tree.column("cp", width=100, stretch=False)
        self._party_tree.heading("buffs", text="Buffs")
        self._party_tree.column("buffs", width=52, stretch=False)
        sy = ttk.Scrollbar(pt, orient=tk.VERTICAL, command=self._party_tree.yview)
        self._party_tree.configure(yscrollcommand=sy.set)
        self._party_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sy.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Separator(f, orient=tk.HORIZONTAL, style=theme.S_SEP).pack(fill=tk.X, padx=12, pady=10)
        ttk.Label(f, text="Combat", style=theme.S_SECTION).pack(pady=(0, 6), padx=12, anchor="w")

        row1 = ttk.Frame(f, style=theme.S_FRAME)
        row1.pack(pady=4, padx=12, anchor="w")

        ttk.Label(row1, text="Range:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._range_var = tk.IntVar(value=1500)
        ttk.Entry(row1, textvariable=self._range_var, width=7, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=(4, 12))

        self._combat_btn_var = tk.StringVar(value="Start auto-combat")
        ttk.Button(row1, textvariable=self._combat_btn_var, command=self._toggle_combat, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(row1, text="Attack nearest", command=self._attack_nearest, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(row1, text="Sit / stand", command=self._sit_stand, style=theme.S_BTN).pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._status_var, style=theme.S_LABEL_MUTED, font=theme.FONT_MONO).pack(
            pady=6, padx=12, anchor="w")

    def _toggle_combat(self) -> None:
        self._combat_running = not self._combat_running
        r = float(self._range_var.get())
        if self._combat_running:
            self._combat_btn_var.set("Stop auto-combat")
            ac = getattr(self.bot, "autocombat_tab", None)
            flush = getattr(ac, "flush_profile_to_engine", None)
            if callable(flush):
                flush()
            cb = getattr(self.bot, "start_auto_combat", None)
            if cb:
                cb(r)
            self._status_var.set(f"Auto-combat ON (range {int(r)})")
        else:
            self._combat_btn_var.set("Start auto-combat")
            cb = getattr(self.bot, "stop_auto_combat", None)
            if cb:
                cb()
            self._status_var.set("Auto-combat OFF")

    def _sit_stand(self) -> None:
        cb = getattr(self.bot, "sit_stand", None)
        if cb:
            cb()
            self._status_var.set("Sit/stand sent")

    def _attack_nearest(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        if not be:
            return
        mob = be.world.get_nearest_mob(float(self._range_var.get()))
        if mob:
            loop = getattr(self.bot, "loop", None)
            if loop:
                loop.call_soon_threadsafe(be.attack, mob.object_id)
            self._status_var.set(f"Attacking: {mob.name or mob.title or str(mob.npc_id)}")
        else:
            self._status_var.set("No mobs in range")

    def _update(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        me = be.world.me if be else None
        if me and me.name:
            self._vars["name"].set(me.name)
            self._vars["level"].set(str(me.level))
            emx = me.effective_max_hp()
            emn = me.effective_max_mp()
            self._vars["hp"].set(f"{me.cur_hp} / {emx}")
            self._vars["mp"].set(f"{me.cur_mp} / {emn}")
            self._vars["pos"].set(f"({me.x}, {me.y}, {me.z})")
            if me.max_cp > 0:
                self._vars["cp"].set(f"{me.cur_cp} / {me.max_cp}")
            elif me.cur_cp:
                self._vars["cp"].set(str(me.cur_cp))
            else:
                self._vars["cp"].set("—")
            self._hp_bar["value"] = me.hp_pct_safe
            self._mp_bar["value"] = me.mp_pct_safe
            diag_cb = getattr(self.bot, "get_combat_diagnostics", None)
            if callable(diag_cb):
                d = diag_cb()
                ph = d.get("phase", "?")
                st = d.get("sitting", "?")
                tg = (d.get("target") or "—") if d.get("auto_combat") else "off"
                self._vars["state"].set(f"{ph} | {st} | {tg}")
            else:
                self._vars["state"].set("—")
        elif be:
            self._vars["cp"].set("—")
            self._vars["state"].set("—")
        if be:
            party = be.world.party_members
            for iid in self._party_tree.get_children():
                self._party_tree.delete(iid)
            if not party:
                self._party_hint.set(
                    "Not in party or waiting for PartySmallWindowAll from server…",
                )
            else:
                self._party_hint.set(
                    "HP/MP/CP from party window + StatusUpdate; buff count from PartySpelled / Abnormal.",
                )
                for oid in sorted(party.keys(), key=lambda x: (party[x].name or "", x)):
                    m = party[oid]
                    label = f"{m.name or '?'} ({m.level})"
                    if me and oid == me.object_id:
                        label = f"{label}  [you]"
                    hp_s = f"{m.cur_hp}/{m.max_hp}" if m.max_hp else str(m.cur_hp)
                    mp_s = f"{m.cur_mp}/{m.max_mp}" if m.max_mp else str(m.cur_mp)
                    if m.max_cp:
                        cp_s = f"{m.cur_cp}/{m.max_cp}"
                    else:
                        cp_s = str(m.cur_cp) if m.cur_cp else "—"
                    nb = len(be.world.abnormal_skill_ids_for_object(oid))
                    self._party_tree.insert("", tk.END, text=label, values=(hp_s, mp_s, cp_s, str(nb)))
        self.frame.after(400, self._update)
