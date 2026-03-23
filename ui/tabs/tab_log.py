"""Log tab — scrolling packet event log with opcode filter."""
import tkinter as tk
from tkinter import ttk
from collections import deque


class LogTab:
    MAX_LINES = 500

    def __init__(self, parent, bot):
        self.bot = bot
        self._lines: deque = deque(maxlen=self.MAX_LINES)
        self._filter = ""
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self) -> None:
        f = self.frame

        ctrl = ttk.Frame(f)
        ctrl.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(ctrl, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._refresh())
        ttk.Entry(ctrl, textvariable=self._filter_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Clear", command=self._clear).pack(side=tk.LEFT)

        self._text = tk.Text(f, font=("Consolas", 9), bg="#0d0d1a", fg="#ccffcc",
                             state=tk.DISABLED, wrap=tk.NONE)
        sb_y = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._text.yview)
        sb_x = ttk.Scrollbar(f, orient=tk.HORIZONTAL, command=self._text.xview)
        self._text.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._text.pack(fill=tk.BOTH, expand=True, padx=(8, 0))

    def log(self, direction: str, opcode: int, name: str, length: int) -> None:
        """Called from asyncio thread — thread-safe via after()."""
        line = f"[{direction}] 0x{opcode:02X} {name:<30} {length:>5}b"
        self._lines.append(line)
        self.frame.after(0, self._append_line, line)

    def _append_line(self, line: str) -> None:
        flt = self._filter_var.get().lower()
        if flt and flt not in line.lower():
            return
        self._text.configure(state=tk.NORMAL)
        self._text.insert(tk.END, line + "\n")
        if int(self._text.index(tk.END).split(".")[0]) > self.MAX_LINES:
            self._text.delete("1.0", "2.0")
        self._text.see(tk.END)
        self._text.configure(state=tk.DISABLED)

    def _refresh(self) -> None:
        flt = self._filter_var.get().lower()
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        for line in self._lines:
            if not flt or flt in line.lower():
                self._text.insert(tk.END, line + "\n")
        self._text.see(tk.END)
        self._text.configure(state=tk.DISABLED)

    def _clear(self) -> None:
        self._lines.clear()
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)
