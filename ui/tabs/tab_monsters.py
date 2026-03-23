"""Monsters tab — nearby mobs list with HP% and distance. Double-click to attack."""
import tkinter as tk
from tkinter import ttk


class MonstersTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._oid_map: dict[str, int] = {}   # tree iid → object_id
        self.frame = ttk.Frame(parent)
        self._build()
        self._update()

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Nearby Monsters",
                  font=("Consolas", 11, "bold")).pack(pady=(8, 4))

        # Range filter row
        top = ttk.Frame(f)
        top.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(top, text="Range:").pack(side=tk.LEFT)
        self._range_var = tk.IntVar(value=2000)
        ttk.Entry(top, textvariable=self._range_var, width=6).pack(
            side=tk.LEFT, padx=(4, 12))
        ttk.Label(top, text="Double-click a mob to attack",
                  foreground="gray").pack(side=tk.LEFT)

        # Table
        cols = ("Name", "NPC ID", "HP%", "Distance")
        self._tree = ttk.Treeview(f, columns=cols, show="headings", height=18)
        widths = {"Name": 150, "NPC ID": 80, "HP%": 60, "Distance": 80}
        for col in cols:
            self._tree.heading(col, text=col)
            self._tree.column(col, width=widths[col], anchor="center")

        sb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                        padx=(8, 0), pady=4)
        sb.pack(side=tk.LEFT, fill=tk.Y, pady=4, padx=(0, 8))

        self._tree.bind("<Double-1>", self._on_double_click)

        self._status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._status_var,
                  font=("Consolas", 9), foreground="#44bb44").pack(pady=2)

    def _on_double_click(self, _event) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        oid = self._oid_map.get(iid)
        if oid is None:
            return
        be = getattr(self.bot, "bot_engine", None)
        loop = getattr(self.bot, "loop", None)
        if be and loop:
            loop.call_soon_threadsafe(be.attack, oid)
            name = self._tree.item(iid)["values"][0]
            self._status_var.set(f"Attacking: {name}")

    def _update(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._oid_map.clear()

        be = getattr(self.bot, "bot_engine", None)
        if be:
            world = be.world
            try:
                r = float(self._range_var.get())
            except (tk.TclError, ValueError):
                r = 2000.0
            mobs = world.get_mobs_in_range(r)
            for mob in mobs:
                display_name = mob.name or mob.title or f"[{mob.npc_id}]"
                dist = f"{world.dist_to(mob):.0f}"
                hp = f"{mob.hp_pct:.0f}%"
                iid = self._tree.insert("", tk.END, values=(
                    display_name, mob.npc_id, hp, dist))
                self._oid_map[iid] = mob.object_id

        self.frame.after(800, self._update)
