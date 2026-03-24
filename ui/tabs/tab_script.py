"""Script tab — load, run, stop, pause .SEC scripts."""
import tkinter as tk
from tkinter import filedialog, ttk

from ui import theme


class ScriptTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._script_path = tk.StringVar(value="")
        self.frame = ttk.Frame(parent, style=theme.S_FRAME)
        self._build()

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Script runner", style=theme.S_TITLE).pack(pady=(10, 6), padx=12, anchor="w")

        row = ttk.Frame(f, style=theme.S_FRAME)
        row.pack(fill=tk.X, padx=12, pady=4)
        ttk.Label(row, text="Script:", style=theme.S_LABEL).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self._script_path, width=48, style=theme.S_ENTRY).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Browse…", command=self._browse, style=theme.S_BTN).pack(side=tk.LEFT)

        ctrl = ttk.Frame(f, style=theme.S_FRAME)
        ctrl.pack(pady=6, padx=12, anchor="w")
        ttk.Button(ctrl, text="Run", command=self._run, style=theme.S_BTN).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Pause", command=self._pause, style=theme.S_BTN).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Stop", command=self._stop, style=theme.S_BTN).pack(side=tk.LEFT, padx=4)

        ttk.Label(f, text="Output", style=theme.S_SECTION).pack(anchor="w", padx=12, pady=(8, 2))
        out_fr = tk.Frame(f, bg=theme.COL_PANEL)
        out_fr.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))
        self._out = tk.Text(
            out_fr, font=theme.FONT_MONO, bg=theme.COL_LOG_BG, fg=theme.COL_WARN,
            state=tk.DISABLED, height=16, highlightthickness=0, insertbackground=theme.COL_TEAL,
        )
        sb = ttk.Scrollbar(out_fr, orient=tk.VERTICAL, command=self._out.yview)
        self._out.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._out.pack(fill=tk.BOTH, expand=True)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select .SEC script",
            filetypes=[("SEC scripts", "*.SEC *.sec"), ("All files", "*.*")]
        )
        if path:
            self._script_path.set(path)

    def _run(self) -> None:
        path = self._script_path.get()
        if not path:
            self._append_output("No script selected.\n")
            return
        runner = getattr(self.bot, "script_runner", None)
        if runner:
            import asyncio
            asyncio.run_coroutine_threadsafe(runner.load_and_run(path), self.bot.loop)
            self._append_output(f"Running: {path}\n")
        else:
            self._append_output("Script engine not initialized yet.\n")

    def _pause(self) -> None:
        runner = getattr(self.bot, "script_runner", None)
        if runner:
            runner.toggle_pause()
            self._append_output("Script paused/resumed.\n")

    def _stop(self) -> None:
        runner = getattr(self.bot, "script_runner", None)
        if runner:
            runner.stop()
            self._append_output("Script stopped.\n")

    def _append_output(self, text: str) -> None:
        self._out.configure(state=tk.NORMAL)
        self._out.insert(tk.END, text)
        self._out.see(tk.END)
        self._out.configure(state=tk.DISABLED)
