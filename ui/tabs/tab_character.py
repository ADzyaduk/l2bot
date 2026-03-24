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
            ("Pos", "pos"),
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
            self._hp_bar["value"] = me.hp_pct_safe
            self._mp_bar["value"] = me.mp_pct_safe
        self.frame.after(500, self._update)
