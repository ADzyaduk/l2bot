"""Script tab — load, run, stop, pause .SEC scripts."""
import tkinter as tk
from tkinter import ttk, filedialog


class ScriptTab:
    def __init__(self, parent, bot):
        self.bot = bot
        self._script_path = tk.StringVar(value="")
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Script Runner", font=("Consolas", 11, "bold")).pack(pady=(8, 4))

        # File picker
        row = ttk.Frame(f)
        row.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(row, text="Script:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self._script_path, width=45).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Browse...", command=self._browse).pack(side=tk.LEFT)

        # Controls
        ctrl = ttk.Frame(f)
        ctrl.pack(pady=4)
        ttk.Button(ctrl, text="▶  Run", command=self._run, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="⏸  Pause", command=self._pause, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="⏹  Stop", command=self._stop, width=10).pack(side=tk.LEFT, padx=4)

        # Output
        ttk.Label(f, text="Output:").pack(anchor="w", padx=8)
        self._out = tk.Text(f, font=("Consolas", 9), bg="#0d0d1a", fg="#ffcc88",
                            state=tk.DISABLED, height=16)
        sb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._out.yview)
        self._out.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8))
        self._out.pack(fill=tk.BOTH, expand=True, padx=(8, 0), pady=(0, 8))

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
