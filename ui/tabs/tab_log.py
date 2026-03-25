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
        # False after prepare_detach() — drop UI log lines (avoids backlog after disconnect / close).
        self._accept_ui_logs: bool = True
        self._hex_after_id: str | None = None
        self.frame = ttk.Frame(parent, style=theme.S_FRAME)
        self._build()

    def prepare_detach(self) -> None:
        """Call before removing log handlers; cancels hex poller and stops accepting lines."""
        self._accept_ui_logs = False
        if self._hex_after_id is not None:
            try:
                self.frame.after_cancel(self._hex_after_id)
            except tk.TclError:
                pass
            self._hex_after_id = None

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
            text="Application: bot, proxies. Packets: S→C, C→S, BOT→S (injected). "
            "Use direction checkboxes + text filter. Hex trace copies raw plaintext from the proxy.",
            style=theme.S_LABEL_MUTED,
            wraplength=760,
        ).pack(anchor="w", padx=12, pady=(0, 6))

        nb = ttk.Notebook(f, style=theme.S_NOTEBOOK)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        app_fr = ttk.Frame(nb, style=theme.S_FRAME)
        pkt_fr = ttk.Frame(nb, style=theme.S_FRAME)
        nb.add(app_fr, text="  Application  ")
        nb.add(pkt_fr, text="  Packets  ")

        self._build_app_pane(app_fr)
        self._build_packet_pane(pkt_fr)

    def _build_app_pane(self, parent: ttk.Frame) -> None:
        ctrl = ttk.Frame(parent, style=theme.S_FRAME)
        ctrl.pack(fill=tk.X, padx=8, pady=(6, 4))
        ttk.Label(ctrl, text="Filter:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._app_filter = tk.StringVar()
        self._app_filter.trace_add("write", lambda *_: self._refresh_app())
        ttk.Entry(ctrl, textvariable=self._app_filter, width=28, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4)
        self._app_errors_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ctrl,
            text="Errors only",
            variable=self._app_errors_only,
            command=self._refresh_app,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=8)
        self._app_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl,
            text="Autoscroll",
            variable=self._app_autoscroll,
            style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Clear", command=self._clear_app, style=theme.S_BTN).pack(
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
        self._app_text = text

    def _build_packet_pane(self, parent: ttk.Frame) -> None:
        ctrl = ttk.Frame(parent, style=theme.S_FRAME)
        ctrl.pack(fill=tk.X, padx=8, pady=(6, 4))
        ttk.Label(ctrl, text="Filter:", style=theme.S_LABEL).pack(side=tk.LEFT)
        self._pkt_filter = tk.StringVar()
        self._pkt_filter.trace_add("write", lambda *_: self._refresh_pkt())
        ttk.Entry(ctrl, textvariable=self._pkt_filter, width=22, style=theme.S_ENTRY).pack(
            side=tk.LEFT, padx=4)
        self._pkt_show_s2c = tk.BooleanVar(value=True)
        self._pkt_show_c2s = tk.BooleanVar(value=True)
        self._pkt_show_bot = tk.BooleanVar(value=True)
        for lab, var in (
            ("S→C", self._pkt_show_s2c),
            ("C→S", self._pkt_show_c2s),
            ("BOT→S", self._pkt_show_bot),
        ):
            ttk.Checkbutton(
                ctrl, text=lab, variable=var, command=self._refresh_pkt, style=theme.S_CHECK,
            ).pack(side=tk.LEFT, padx=2)
        self._pkt_debug = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            ctrl, text="Debug C→S", variable=self._pkt_debug,
            command=self._set_packet_log_level, style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=8)
        self._pkt_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ctrl, text="Autoscroll", variable=self._pkt_autoscroll, style=theme.S_CHECK,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="Clear", command=self._clear_pkt, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=4)

        split = ttk.Panedwindow(parent, orient=tk.VERTICAL)
        split.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        text_fr = tk.Frame(split, bg=theme.COL_PANEL)
        split.add(text_fr, weight=3)
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
        self._pkt_text = text

        hex_fr = ttk.LabelFrame(split, text="Recent plaintext (opcode + payload hex)", style=theme.S_LF)
        split.add(hex_fr, weight=1)
        hf = ttk.Frame(hex_fr, style=theme.S_FRAME)
        hf.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._hex_list = tk.Listbox(
            hf, height=5, font=theme.FONT_MONO, bg=theme.COL_LOG_BG, fg=theme.COL_LOG_FG,
            exportselection=False,
        )
        sb_h = ttk.Scrollbar(hf, orient=tk.VERTICAL, command=self._hex_list.yview)
        self._hex_list.config(yscrollcommand=sb_h.set)
        self._hex_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_h.pack(side=tk.RIGHT, fill=tk.Y)
        hb = ttk.Frame(hex_fr, style=theme.S_FRAME)
        hb.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(hb, text="Copy selected hex", command=self._copy_selected_hex, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=2)
        ttk.Button(hb, text="Refresh trace", command=self._refresh_hex_trace, style=theme.S_BTN).pack(
            side=tk.LEFT, padx=2)
        self._schedule_hex_tick()

    def _schedule_hex_tick(self) -> None:
        if not self._accept_ui_logs:
            return
        try:
            self._hex_after_id = self.frame.after(800, self._tick_hex_trace)
        except tk.TclError:
            self._hex_after_id = None

    def _tick_hex_trace(self) -> None:
        self._hex_after_id = None
        if not self._accept_ui_logs:
            return
        try:
            if not self.frame.winfo_exists():
                return
            self._refresh_hex_trace()
        except tk.TclError:
            return
        except Exception:
            pass
        self._schedule_hex_tick()

    def _refresh_hex_trace(self) -> None:
        if not self._accept_ui_logs:
            return
        bot = getattr(self.bot, "get_packet_trace", None)
        rows = bot() if callable(bot) else []
        self._hex_list.delete(0, tk.END)
        for direction, opcode, name, hx in rows:
            self._hex_list.insert(tk.END, f"{direction} 0x{opcode:02X} {name}  {hx}")

    def _copy_selected_hex(self) -> None:
        sel = self._hex_list.curselection()
        if not sel:
            return
        line = self._hex_list.get(sel[0])
        parts = line.split(None, 3)
        hx = parts[-1] if parts else line
        self.frame.clipboard_clear()
        self.frame.clipboard_append(hx)

    def _set_packet_log_level(self) -> None:
        from ui.log_handler import PACKET_LOGGER_NAME
        pkt = logging.getLogger(PACKET_LOGGER_NAME)
        pkt.setLevel(logging.DEBUG if self._pkt_debug.get() else logging.INFO)

    def _app_line_visible(self, line: str) -> bool:
        flt = self._app_filter.get().lower().strip()
        if flt and flt not in line.lower():
            return False
        if self._app_errors_only.get():
            return "[ERROR]" in line or "[CRITICAL]" in line
        return True

    def _pkt_line_visible(self, line: str) -> bool:
        flt = self._pkt_filter.get().lower().strip()
        if flt and flt not in line.lower():
            return False
        lo = line.lower()
        if "[s→c]" in line or "s→c" in lo:
            return self._pkt_show_s2c.get()
        if "[bot→s]" in line or "bot→s" in lo:
            return self._pkt_show_bot.get()
        if "[c→s]" in line or "c→s" in lo:
            return self._pkt_show_c2s.get()
        return True

    def append_app_line(self, line: str) -> None:
        if not self._accept_ui_logs:
            return
        self._app_lines.append(line)
        if not self._app_line_visible(line):
            return
        try:
            self._append_to_text(self._app_text, line, autoscroll=self._app_autoscroll.get())
        except tk.TclError:
            pass

    def append_packet_line(self, line: str) -> None:
        if not self._accept_ui_logs:
            return
        self._pkt_lines.append(line)
        if not self._pkt_line_visible(line):
            return
        try:
            self._append_to_text(self._pkt_text, line, autoscroll=self._pkt_autoscroll.get())
        except tk.TclError:
            pass

    def _append_to_text(self, widget: tk.Text, line: str, *, autoscroll: bool = True) -> None:
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, line + "\n")
        max_vis = 6000
        end_ln = int(widget.index(tk.END).split(".")[0])
        if end_ln > max_vis:
            widget.delete("1.0", f"{end_ln - max_vis}.0")
        if autoscroll:
            widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _refresh_app(self) -> None:
        self._app_text.configure(state=tk.NORMAL)
        self._app_text.delete("1.0", tk.END)
        for line in self._app_lines:
            if self._app_line_visible(line):
                self._app_text.insert(tk.END, line + "\n")
        if self._app_autoscroll.get():
            self._app_text.see(tk.END)
        self._app_text.configure(state=tk.DISABLED)

    def _refresh_pkt(self) -> None:
        self._pkt_text.configure(state=tk.NORMAL)
        self._pkt_text.delete("1.0", tk.END)
        for line in self._pkt_lines:
            if self._pkt_line_visible(line):
                self._pkt_text.insert(tk.END, line + "\n")
        if self._pkt_autoscroll.get():
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
