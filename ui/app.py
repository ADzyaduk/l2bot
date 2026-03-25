"""
L2Bot main window — tabbed UI with shared industrial/dark theme.
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk

try:
    import customtkinter as ctk
    USE_CTK = True
except ImportError:
    USE_CTK = False

from ui import theme
from ui.log_handler import attach_ui_logging, detach_ui_logging

log = logging.getLogger(__name__)

_UI_STATE = Path(__file__).resolve().parents[1] / "config" / "ui_state.json"


class L2BotApp:
    """Main application window."""

    def __init__(self, bot):
        self.bot = bot

        if USE_CTK:
            ctk.set_appearance_mode("dark")
            self.root = ctk.CTk(fg_color=theme.COL_BG)
        else:
            self.root = tk.Tk()
            self.root.configure(bg=theme.COL_BG)

        self.root.title("L2Bot — Lineage 2 MITM")
        self._restore_geometry()
        try:
            self.root.minsize(1024, 680)
        except tk.TclError:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        theme.setup_ttk_styles(self.root)
        self._build_ui()
        self._start_status_update()

    def _restore_geometry(self) -> None:
        try:
            if _UI_STATE.is_file():
                st = json.loads(_UI_STATE.read_text(encoding="utf-8"))
                geo = st.get("geometry")
                if geo:
                    self.root.geometry(geo)
                    return
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        self.root.geometry("1100x720")

    def _save_ui_state(self) -> None:
        try:
            _UI_STATE.parent.mkdir(parents=True, exist_ok=True)
            idx = getattr(self, "_notebook", None)
            tab_i = 0
            if idx is not None:
                try:
                    tab_i = idx.index(idx.select())
                except tk.TclError:
                    pass
            _UI_STATE.write_text(
                json.dumps(
                    {"geometry": self.root.geometry(), "tab": tab_i},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=theme.COL_BG)
        outer.pack(fill=tk.BOTH, expand=True)

        rail = tk.Frame(outer, bg=theme.COL_RAIL, height=4)
        rail.pack(side=tk.TOP, fill=tk.X)

        status_frame = tk.Frame(outer, bg=theme.COL_STATUS_BG, height=36)
        status_frame.pack(side=tk.TOP, fill=tk.X)

        self._status_var = tk.StringVar(value="Waiting for client connection…")
        tk.Label(
            status_frame,
            textvariable=self._status_var,
            bg=theme.COL_STATUS_BG,
            fg=theme.COL_TEAL,
            font=theme.FONT_MONO,
            anchor="w",
            padx=12,
            pady=6,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(
            status_frame,
            text="INTERLUDE",
            bg=theme.COL_STATUS_BG,
            fg=theme.COL_ACCENT_DIM,
            font=theme.FONT_SMALL,
            padx=12,
        ).pack(side=tk.RIGHT)

        nb_container = tk.Frame(outer, bg=theme.COL_BG)
        nb_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        notebook = ttk.Notebook(nb_container, style=theme.S_NOTEBOOK)
        notebook.pack(fill=tk.BOTH, expand=True)
        self._notebook = notebook

        from ui.tabs.tab_character import CharacterTab
        from ui.tabs.tab_monsters import MonstersTab
        from ui.tabs.tab_autocombat import AutoCombatTab
        from ui.tabs.tab_buffs import BuffsTab
        from ui.tabs.tab_log import LogTab
        from ui.tabs.tab_settings import SettingsTab
        from ui.tabs.tab_script import ScriptTab

        self._char_tab = CharacterTab(notebook, self.bot)
        self._monsters_tab = MonstersTab(notebook, self.bot)
        self._autocombat_tab = AutoCombatTab(notebook, self.bot)
        self._buffs_tab = BuffsTab(notebook, self.bot)
        self._script_tab = ScriptTab(notebook, self.bot)
        self._log_tab = LogTab(notebook, self.bot)
        self._settings_tab = SettingsTab(notebook, self.bot)

        for tab, title in (
            (self._char_tab.frame, "Character"),
            (self._monsters_tab.frame, "Monsters"),
            (self._autocombat_tab.frame, "Auto combat"),
            (self._buffs_tab.frame, "Buffs"),
            (self._script_tab.frame, "Script"),
            (self._log_tab.frame, "Log"),
            (self._settings_tab.frame, "Settings"),
        ):
            notebook.add(tab, text=f"  {title}  ")

        self.bot.log_tab = self._log_tab
        self.bot.autocombat_tab = self._autocombat_tab
        self.bot.on_character_profiles_changed = self._on_character_profiles_changed
        attach_ui_logging(self._log_tab)

        try:
            if _UI_STATE.is_file():
                st = json.loads(_UI_STATE.read_text(encoding="utf-8"))
                ti = int(st.get("tab", 0))
                if 0 <= ti < notebook.index("end"):
                    notebook.select(ti)
        except (OSError, ValueError, json.JSONDecodeError, tk.TclError):
            pass

    def _on_character_profiles_changed(self) -> None:
        """BotEngine may call from asyncio thread — marshal to Tk main thread."""
        try:
            self.root.after(0, self._do_character_profiles_changed)
        except tk.TclError:
            pass

    def _do_character_profiles_changed(self) -> None:
        for tab in (
            getattr(self, "_autocombat_tab", None),
            getattr(self, "_buffs_tab", None),
        ):
            if tab is not None and hasattr(tab, "refresh_profile_from_disk"):
                tab.refresh_profile_from_disk()

    def _start_status_update(self) -> None:
        self._update_status()

    def _update_status(self) -> None:
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        gp = getattr(self.bot, "game_proxy", None)
        gs = gp.session if gp else None
        extra = ""
        diag_cb = getattr(self.bot, "get_combat_diagnostics", None)
        if callable(diag_cb):
            d = diag_cb()
            br = d.get("buff_rules", 0)
            cr = d.get("combat_rules", 0)
            extra = f"  |  rules: buffs={br} combat={cr}"
            if d.get("auto_combat"):
                ph = d.get("phase", "?")
                tg = d.get("target") or "—"
                extra += f"  |  combat: {ph}  {tg}"
        if gs and gs.crypto_initialized:
            self._status_var.set("Connected — game proxy active" + extra)
        elif self.bot.login_session.login_ok1:
            self._status_var.set("Authenticated — waiting for game connection")
        else:
            self._status_var.set("Waiting for client connection…")
        try:
            self.root.after(1000, self._update_status)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        self._save_ui_state()
        try:
            detach_ui_logging(self._log_tab)
        except Exception:
            pass
        self.bot.stop()
        self.root.destroy()

    def mainloop(self) -> None:
        self.root.mainloop()
