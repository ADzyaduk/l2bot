"""Log tab — application log and packet log in separate panes (searchable, capped)."""
from __future__ import annotations

import logging
import tkinter as tk
from collections import deque
from tkinter import ttk

from ui import theme


class LogTab:
    MAX_APP_LINES = 2500
    MAX_PKT_LINES = 4000

    def __init__(self, parent, bot):
        self.bot = bot
        self._app_lines: deque[str] = deque(maxlen=self.MAX_APP_LINES)
        self._pkt_lines: deque[str] = deque(maxlen=self.MAX_PKT_LINES)
        self._ui_handlers: list[logging.Handler] = []
        self.frame = ttk.Frame(parent, style=theme.S_FRAME)
        self._build()

    def register_handlers(self, *handlers: logging.Handler) -> None:
        self._ui_handlers.extend(handlers)

    def take_handlers(self) -> list[logging.Handler]:
        h = self._ui_handlers[:]
        self._ui_handlers.clear()
        return h

    def _build(self) -> None:
        f = self.frame
        ttk.Label(f, text="Logs", style=theme.S_TITLE).pack(anchor="w", padx=12, pady=(10, 4))
        ttk.Label(
            f,
            text="Application: bot, proxies (except per-packet lines). Packets: S→C and C→S. "
            "C→S for skills/target/action (0x39, 0x04, …) logs plain= at INFO; not move spam. "
            "Check «Debug C→S» for every client packet. Console: WARNING+.",
            style=theme.S_LABEL_MUTED,
            wraplength=760,
        ).pack(anchor="w", padx=12, pady=(0, 6))

        nb = ttk.Notebook(f, style=theme.S_NOTEBOOK)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        app_fr = ttk.Frame(nb, style=theme.S_FRAME)
        pkt_fr = ttk.Frame(nb, style=theme.S_FRAME)
        nb.add(app_fr, text="  Application  ")
        nb.add(pkt_fr, text="  Packets  ")

        self._build_pane(app_fr, "app")
        self._build_pane(pkt_fr, "packets")

    def _build_pane(self, parent: ttk.Frame, which: str) -> None:
        ctrl = ttk.Frame(parent, style=theme.S_FRAME)
        ctrl.pack(fill=tk.X, padx=8, pady=(6, 4))
        ttk.Label(ctrl, text="Filter:", style=theme.S_LABEL).pack(side=tk.LEFT)
        if which == "app":
            self._app_filter = tk.StringVar()
            self._app_filter.trace_add("write", lambda *_: self._refresh_app())
            ttk.Entry(ctrl, textvariable=self._app_filter, width=28, style=theme.S_ENTRY).pack(
                side=tk.LEFT, padx=4)
            ttk.Button(ctrl, text="Clear", command=self._clear_app, style=theme.S_BTN).pack(
                side=tk.LEFT, padx=4)
        else:
            self._pkt_filter = tk.StringVar()
            self._pkt_filter.trace_add("write", lambda *_: self._refresh_pkt())
            ttk.Entry(ctrl, textvariable=self._pkt_filter, width=28, style=theme.S_ENTRY).pack(
                side=tk.LEFT, padx=4)
            self._pkt_debug = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                ctrl, text="Debug C→S", variable=self._pkt_debug,
                command=self._set_packet_log_level, style=theme.S_CHECK,
            ).pack(side=tk.LEFT, padx=8)
            ttk.Button(ctrl, text="Clear", command=self._clear_pkt, style=theme.S_BTN).pack(
                side=tk.LEFT, padx=4)

        text_fr = tk.Frame(parent, bg=theme.COL_PANEL)
        text_fr.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        text = tk.Text(
            text_fr, font=theme.FONT_MONO, bg=theme.COL_LOG_BG, fg=theme.COL_LOG_FG,
            insertbackground=theme.COL_TEAL, state=tk.DISABLED, wrap=tk.NONE, highlightthickness=0,
        )
        sb_y = ttk.Scrollbar(text_fr, orient=tk.VERTICAL, command=text.yview)
        sb_x = ttk.Scrollbar(text_fr, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)
        text.pack(fill=tk.BOTH, expand=True)

        if which == "app":
            self._app_text = text
        else:
            self._pkt_text = text

    def _set_packet_log_level(self) -> None:
        from ui.log_handler import PACKET_LOGGER_NAME
        pkt = logging.getLogger(PACKET_LOGGER_NAME)
        pkt.setLevel(logging.DEBUG if self._pkt_debug.get() else logging.INFO)

    def append_app_line(self, line: str) -> None:
        self._app_lines.append(line)
        flt = self._app_filter.get().lower()
        if flt and flt not in line.lower():
            return
        self._append_to_text(self._app_text, line)

    def append_packet_line(self, line: str) -> None:
        self._pkt_lines.append(line)
        flt = self._pkt_filter.get().lower()
        if flt and flt not in line.lower():
            return
        self._append_to_text(self._pkt_text, line)

    def _append_to_text(self, widget: tk.Text, line: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, line + "\n")
        # trim visible widget if huge (deque already caps memory of list)
        max_vis = 6000
        end_ln = int(widget.index(tk.END).split(".")[0])
        if end_ln > max_vis:
            widget.delete("1.0", f"{end_ln - max_vis}.0")
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _refresh_app(self) -> None:
        flt = self._app_filter.get().lower()
        self._app_text.configure(state=tk.NORMAL)
        self._app_text.delete("1.0", tk.END)
        for line in self._app_lines:
            if not flt or flt in line.lower():
                self._app_text.insert(tk.END, line + "\n")
        self._app_text.see(tk.END)
        self._app_text.configure(state=tk.DISABLED)

    def _refresh_pkt(self) -> None:
        flt = self._pkt_filter.get().lower()
        self._pkt_text.configure(state=tk.NORMAL)
        self._pkt_text.delete("1.0", tk.END)
        for line in self._pkt_lines:
            if not flt or flt in line.lower():
                self._pkt_text.insert(tk.END, line + "\n")
        self._pkt_text.see(tk.END)
        self._pkt_text.configure(state=tk.DISABLED)

    def _clear_app(self) -> None:
        self._app_lines.clear()
        self._app_text.configure(state=tk.NORMAL)
        self._app_text.delete("1.0", tk.END)
        self._app_text.configure(state=tk.DISABLED)

    def _clear_pkt(self) -> None:
        self._pkt_lines.clear()
        self._pkt_text.configure(state=tk.NORMAL)
        self._pkt_text.delete("1.0", tk.END)
        self._pkt_text.configure(state=tk.DISABLED)

    def log(self, direction: str, opcode: int, name: str, length: int) -> None:
        """Legacy hook — same as packet pane."""
        line = f"[{direction}] 0x{opcode:02X} {name:<30} {length:>5}b"
        self.append_packet_line(line)
