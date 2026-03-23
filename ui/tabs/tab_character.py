"""Character tab — HP/MP display + combat controls."""
import tkinter as tk
from tkinter import ttk


class CharacterTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._combat_running = False
        self.frame = ttk.Frame(parent)
        self._build()
        self._update()

    def _build(self) -> None:
        f = self.frame

        # ---- Character info ----
        ttk.Label(f, text="Character", font=("Consolas", 11, "bold")).pack(pady=(8, 4))

        grid = ttk.Frame(f)
        grid.pack(fill=tk.X, padx=20, pady=4)

        self._vars = {}
        for row, (label, key) in enumerate([
            ("Name",  "name"),
            ("Level", "level"),
            ("HP",    "hp"),
            ("MP",    "mp"),
            ("Pos",   "pos"),
        ]):
            ttk.Label(grid, text=label + ":", width=7, anchor="e").grid(
                row=row, column=0, sticky="e", pady=2, padx=(0, 8))
            var = tk.StringVar(value="—")
            self._vars[key] = var
            ttk.Label(grid, textvariable=var, anchor="w",
                      font=("Consolas", 10)).grid(row=row, column=1, sticky="w")

        # ---- HP/MP bars ----
        bar_frame = ttk.Frame(f)
        bar_frame.pack(fill=tk.X, padx=20, pady=(6, 2))

        ttk.Label(bar_frame, text="HP", width=4, anchor="e").grid(row=0, column=0)
        self._hp_bar = ttk.Progressbar(bar_frame, length=320, maximum=100)
        self._hp_bar.grid(row=0, column=1, padx=8, pady=2)

        ttk.Label(bar_frame, text="MP", width=4, anchor="e").grid(row=1, column=0)
        self._mp_bar = ttk.Progressbar(bar_frame, length=320, maximum=100)
        self._mp_bar.grid(row=1, column=1, padx=8, pady=2)

        # ---- Combat controls ----
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=16, pady=10)
        ttk.Label(f, text="Combat", font=("Consolas", 11, "bold")).pack(pady=(0, 6))

        row1 = ttk.Frame(f)
        row1.pack(pady=4)

        ttk.Label(row1, text="Range:").pack(side=tk.LEFT)
        self._range_var = tk.IntVar(value=1500)
        ttk.Entry(row1, textvariable=self._range_var, width=6).pack(side=tk.LEFT, padx=(4, 12))

        self._combat_btn_var = tk.StringVar(value="▶  Start Auto-Combat")
        ttk.Button(row1, textvariable=self._combat_btn_var,
                   command=self._toggle_combat, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(row1, text="Attack Nearest",
                   command=self._attack_nearest, width=14).pack(side=tk.LEFT, padx=4)
        ttk.Button(row1, text="Sit/Stand",
                   command=self._sit_stand, width=10).pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._status_var,
                  font=("Consolas", 9), foreground="#44bb44").pack(pady=4)

    # ---- combat button handlers ----

    def _toggle_combat(self) -> None:
        self._combat_running = not self._combat_running
        r = float(self._range_var.get())
        if self._combat_running:
            self._combat_btn_var.set("⏹  Stop Auto-Combat")
            cb = getattr(self.bot, "start_auto_combat", None)
            if cb:
                cb(r)
            self._status_var.set(f"Auto-combat ON  (range {int(r)})")
        else:
            self._combat_btn_var.set("▶  Start Auto-Combat")
            cb = getattr(self.bot, "stop_auto_combat", None)
            if cb:
                cb()
            self._status_var.set("Auto-combat OFF")

    def _sit_stand(self) -> None:
        cb = getattr(self.bot, "sit_stand", None)
        if cb:
            cb()
            self._status_var.set("Sit/Stand sent")

    def _attack_nearest(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        if not be:
            return
        mob = be.world.get_nearest_mob(float(self._range_var.get()))
        if mob:
            loop = getattr(self.bot, "loop", None)
            if loop:
                loop.call_soon_threadsafe(be.attack, mob.object_id)
            self._status_var.set(
                f"Attacking: {mob.name or mob.title or str(mob.npc_id)}")
        else:
            self._status_var.set("No mobs in range")

    # ---- periodic update ----

    def _update(self) -> None:
        be = getattr(self.bot, "bot_engine", None)
        me = be.world.me if be else None
        if me and me.name:
            self._vars["name"].set(me.name)
            self._vars["level"].set(str(me.level))
            self._vars["hp"].set(f"{me.cur_hp} / {me.max_hp}")
            self._vars["mp"].set(f"{me.cur_mp} / {me.max_mp}")
            self._vars["pos"].set(f"({me.x}, {me.y}, {me.z})")
            self._hp_bar["value"] = me.hp_pct
            self._mp_bar["value"] = me.mp_pct
        self.frame.after(500, self._update)
