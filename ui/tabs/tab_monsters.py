"""Monsters tab — nearby mobs list with HP% and distance. Double-click to attack."""
import tkinter as tk
from tkinter import ttk

from ui import theme


class MonstersTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._oid_map: dict[str, int] = {}
        self.frame = ttk.Frame(parent, style=theme.S_FRAME)
        self._build()
        self._update()

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Nearby monsters", style=theme.S_TITLE).pack(pady=(10, 6), padx=12, anchor="w")

        top = ttk.Frame(f, style=theme.S_FRAME)
        top.pack(fill=tk.X, padx=12, pady=4)
        ttk.Label(top, text="Range:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._range_var = tk.IntVar(value=2000)
        ttk.Entry(top, textvariable=self._range_var, width=7, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=(4, 12))
        self._show_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            top,
            text="Show all NPCs in range (debug)",
            variable=self._show_all_var,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(top, text="Double-click to attack", style=theme.S_LABEL_MUTED).pack(side=tk.LEFT)

        self._counts_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._counts_var, style=theme.S_LABEL_MUTED, font=theme.FONT_MONO).pack(
            padx=12, anchor="w", pady=(0, 2))

        cols = ("Name", "NPC ID", "HP%", "Atk", "Distance")
        self._tree = ttk.Treeview(f, columns=cols, show="headings", height=18, style=theme.S_TREE)
        widths = {"Name": 170, "NPC ID": 72, "HP%": 52, "Atk": 40, "Distance": 72}
        for col in cols:
            self._tree.heading(col, text=col)
            self._tree.column(col, width=widths[col], anchor="center")

        sb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=6)
        sb.pack(side=tk.LEFT, fill=tk.Y, pady=6, padx=(0, 12))

        self._tree.bind("<Double-1>", self._on_double_click)

        self._status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self._status_var, style=theme.S_LABEL_MUTED, font=theme.FONT_MONO).pack(
            pady=4, padx=12, anchor="w")

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
            show_all = self._show_all_var.get()
            mobs = world.get_mobs_in_range(r, attackable_only=not show_all)
            atk_in_range = len(world.get_mobs_in_range(r, attackable_only=True))
            any_in_range = len(world.get_mobs_in_range(r, attackable_only=False))
            total_world = len(world.npcs)
            me = world.me
            self._counts_var.set(
                f"world.npcs={total_world}  in_range(all)={any_in_range}  attackable_in_range={atk_in_range}  "
                f"me=({me.x},{me.y})"
            )
            for mob in mobs:
                display_name = mob.name or mob.title or f"[{mob.npc_id}]"
                if show_all and not mob.is_attackable:
                    display_name = "[peace] " + display_name
                dist = f"{world.dist_to(mob):.0f}"
                hp = f"{mob.hp_pct:.0f}%"
                atk = "yes" if mob.is_attackable else "no"
                iid = self._tree.insert(
                    "", tk.END, values=(display_name, mob.npc_id, hp, atk, dist),
                )
                self._oid_map[iid] = mob.object_id
        else:
            self._counts_var.set("no bot_engine — start proxy and connect client")

        self.frame.after(800, self._update)
