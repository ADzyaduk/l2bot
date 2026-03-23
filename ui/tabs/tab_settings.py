"""Settings tab — server config, chronicle, l2 path, log level."""
import configparser
import tkinter as tk
from tkinter import ttk, filedialog


class SettingsTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self.frame = ttk.Frame(parent)
        self._vars: dict[str, tk.StringVar] = {}
        self._build()
        self._load_from_cfg()

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Settings", font=("Consolas", 11, "bold")).pack(pady=(8, 4))

        grid = ttk.LabelFrame(f, text="Server")
        grid.pack(fill=tk.X, padx=16, pady=4)

        fields = [
            ("Login Server Host", "server.login_host"),
            ("Login Server Port", "server.login_port"),
            ("Game Server Host", "server.game_host"),
            ("Game Server Port", "server.game_port"),
        ]
        for row, (label, key) in enumerate(fields):
            ttk.Label(grid, text=label + ":", width=22, anchor="e").grid(
                row=row, column=0, sticky="e", pady=2, padx=(4, 6)
            )
            var = tk.StringVar()
            self._vars[key] = var
            ttk.Entry(grid, textvariable=var, width=24).grid(row=row, column=1, sticky="w")

        # Chronicle
        chron_frame = ttk.LabelFrame(f, text="Chronicle")
        chron_frame.pack(fill=tk.X, padx=16, pady=4)
        self._vars["chronicle.name"] = tk.StringVar(value="interlude")
        ttk.OptionMenu(chron_frame, self._vars["chronicle.name"],
                       "interlude", "interlude", "c4", "h5").pack(padx=8, pady=4, anchor="w")

        # L2 Client
        client_frame = ttk.LabelFrame(f, text="L2 Client")
        client_frame.pack(fill=tk.X, padx=16, pady=4)
        row2 = ttk.Frame(client_frame)
        row2.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(row2, text="L2.exe path:", width=14, anchor="e").pack(side=tk.LEFT)
        self._vars["client.l2_path"] = tk.StringVar()
        ttk.Entry(row2, textvariable=self._vars["client.l2_path"], width=40).pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="Browse...", command=self._browse_l2).pack(side=tk.LEFT)

        # Buttons
        btn_frame = ttk.Frame(f)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="Save", command=self._save, width=12).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Reload", command=self._load_from_cfg, width=12).pack(side=tk.LEFT, padx=6)

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
        tk.messagebox.showinfo("Settings", "Settings saved. Restart to apply changes.")
