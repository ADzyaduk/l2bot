"""Settings tab — server config, chronicle, l2 path, log level."""
import configparser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui import theme


class SettingsTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self.frame = ttk.Frame(parent, style=theme.S_FRAME)
        self._vars: dict[str, tk.StringVar] = {}
        self._build()
        self._load_from_cfg()

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Settings", style=theme.S_TITLE).pack(pady=(10, 6), padx=12, anchor="w")

        grid = ttk.LabelFrame(f, text="Server", style=theme.S_LF)
        grid.pack(fill=tk.X, padx=12, pady=6)

        fields = [
            ("Login Server Host", "server.login_host"),
            ("Login Server Port", "server.login_port"),
            ("Game Server Host", "server.game_host"),
            ("Game Server Port", "server.game_port"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(grid, text=label + ":", style=theme.S_LABEL, width=22, anchor="e").grid(
                row=row, column=0, sticky="e", pady=3, padx=(8, 6)
            )
            var = tk.StringVar()
            self._vars[key] = var
            ttk.Entry(grid, textvariable=var, width=28, style=theme.S_ENTRY).grid(row=row, column=1, sticky="w", pady=3)

        chron_frame = ttk.LabelFrame(f, text="Chronicle", style=theme.S_LF)
        chron_frame.pack(fill=tk.X, padx=12, pady=6)
        self._vars["chronicle.name"] = tk.StringVar(value="interlude")
        ttk.OptionMenu(chron_frame, self._vars["chronicle.name"],
                       "interlude", "interlude", "c4", "h5").pack(padx=10, pady=6, anchor="w")

        client_frame = ttk.LabelFrame(f, text="L2 client", style=theme.S_LF)
        client_frame.pack(fill=tk.X, padx=12, pady=6)
        row2 = ttk.Frame(client_frame, style=theme.S_FRAME)
        row2.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(row2, text="L2.exe path:", style=theme.S_LABEL, width=14, anchor="e").pack(side=tk.LEFT)
        self._vars["client.l2_path"] = tk.StringVar()
        ttk.Entry(row2, textvariable=self._vars["client.l2_path"], width=42, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(row2, text="Browse…", command=self._browse_l2, style=theme.S_BTN).pack(side=tk.LEFT)

        btn_frame = ttk.Frame(f, style=theme.S_FRAME)
        btn_frame.pack(pady=12)
        ttk.Button(btn_frame, text="Save", command=self._save, style=theme.S_BTN).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Reload", command=self._load_from_cfg, style=theme.S_BTN).pack(side=tk.LEFT, padx=6)

    def _browse_l2(self) -> None:
        path = filedialog.askopenfilename(
            title="Select L2.exe",
            filetypes=[("Lineage 2 client", "L2.exe"), ("Executables", "*.exe")]
        )
        if path:
            self._vars["client.l2_path"].set(path)

    def _load_from_cfg(self) -> None:
        cfg = self.bot.cfg
        mapping = {
            "server.login_host": ("server", "login_host", "127.0.0.1"),
            "server.login_port": ("server", "login_port", "2106"),
            "server.game_host": ("server", "game_host", "127.0.0.1"),
            "server.game_port": ("server", "game_port", "7777"),
            "chronicle.name": ("chronicle", "name", "interlude"),
            "client.l2_path": ("client", "l2_path", ""),
        }
        for var_key, (section, option, default) in mapping.items():
            if var_key in self._vars:
                self._vars[var_key].set(cfg.get(section, option, fallback=default))

    def _save(self) -> None:
        cfg = self.bot.cfg
        mapping = {
            "server.login_host": ("server", "login_host"),
            "server.login_port": ("server", "login_port"),
            "server.game_host": ("server", "game_host"),
            "server.game_port": ("server", "game_port"),
            "chronicle.name": ("chronicle", "name"),
            "client.l2_path": ("client", "l2_path"),
        }
        for var_key, (section, option) in mapping.items():
            if var_key in self._vars:
                if not cfg.has_section(section):
                    cfg.add_section(section)
                cfg.set(section, option, self._vars[var_key].get())
        with open("config/settings.ini", "w", encoding="utf-8") as fh:
            cfg.write(fh)
        messagebox.showinfo("Settings", "Settings saved. Restart to apply changes.")
