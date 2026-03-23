"""
L2Bot main window with tabbed layout.

Built with customtkinter for a modern look.
Falls back to standard tkinter if customtkinter is not installed.

Tab structure mirrors L2Walker's confirmed UI (from enUS.lng analysis):
  Character | Monsters | Inventory | Skills | Script | Map | Log | Settings
"""
import logging
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    USE_CTK = True
except ImportError:
    USE_CTK = False

log = logging.getLogger(__name__)


class L2BotApp:
    """Main application window."""

    def __init__(self, bot):
        self.bot = bot

        if USE_CTK:
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()

        self.root.title("L2Bot v0.1 — Lineage 2 MITM Proxy")
        self.root.geometry("900x600")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._start_status_update()

    def _build_ui(self) -> None:
        # ---- Top status bar ----
        status_frame = tk.Frame(self.root, bg="#1a1a2e", height=30)
        status_frame.pack(side=tk.TOP, fill=tk.X)

        self._status_var = tk.StringVar(value="Status: Waiting for client connection...")
        status_lbl = tk.Label(
            status_frame, textvariable=self._status_var,
            bg="#1a1a2e", fg="#00ff88", font=("Consolas", 9),
            anchor="w", padx=8
        )
        status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ---- Notebook (tabs) ----
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Import tab modules lazily
        from ui.tabs.tab_character import CharacterTab
        from ui.tabs.tab_monsters import MonstersTab
        from ui.tabs.tab_log import LogTab
        from ui.tabs.tab_settings import SettingsTab
        from ui.tabs.tab_script import ScriptTab

        self._char_tab = CharacterTab(notebook, self.bot)
        self._monsters_tab = MonstersTab(notebook, self.bot)
        self._log_tab = LogTab(notebook, self.bot)
        self._script_tab = ScriptTab(notebook, self.bot)
        self._settings_tab = SettingsTab(notebook, self.bot)

        notebook.add(self._char_tab.frame, text="  Character  ")
        notebook.add(self._monsters_tab.frame, text="  Monsters  ")
        notebook.add(self._script_tab.frame, text="  Script  ")
        notebook.add(self._log_tab.frame, text="  Log  ")
        notebook.add(self._settings_tab.frame, text="  Settings  ")

        # Expose log tab for packet logging
        self.bot.log_tab = self._log_tab

    def _start_status_update(self) -> None:
        self._update_status()

    def _update_status(self) -> None:
        gp = getattr(self.bot, "game_proxy", None)
        gs = gp.session if gp else None
        if gs and gs.crypto_initialized:
            self._status_var.set("Status: Connected — Game Server proxy active")
        elif self.bot.login_session.login_ok1:
            self._status_var.set("Status: Authenticated — waiting for game connection")
        else:
            self._status_var.set("Status: Waiting for client connection...")
        self.root.after(1000, self._update_status)

    def _on_close(self) -> None:
        self.bot.stop()
        self.root.destroy()

    def mainloop(self) -> None:
        self.root.mainloop()
