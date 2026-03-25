"""
Bridge Python logging → Log tab (main Tk thread).

Packet traffic uses logger name "l2bot.packets" so it can be shown separately
from bot/proxy messages.

Logging runs on the asyncio / proxy threads; each log line used to schedule a
separate Tk after(0), so hundreds of lines could queue and appear seconds
after disconnect. We batch flushes and stop accepting lines on prepare_detach().
"""
from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

import tkinter as tk

if TYPE_CHECKING:
    from ui.tabs.tab_log import LogTab

PACKET_LOGGER_NAME = "l2bot.packets"


class _AppLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(PACKET_LOGGER_NAME)


class _PacketLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(PACKET_LOGGER_NAME)


class TkinterLogHandler(logging.Handler):
    """Thread-safe batched append via Tk after() — avoids huge delayed backlogs."""

    _MAX_QUEUE = 2500
    _BATCH = 100

    def __init__(self, log_tab: "LogTab", *, target: str) -> None:
        super().__init__()
        self._tab = log_tab
        self._target = target  # "app" | "packets"
        self._pending: deque[tuple[str, str]] = deque(maxlen=self._MAX_QUEUE)
        self._flush_scheduled = False
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return

        self._pending.append((self._target, msg))
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        try:
            self._tab.frame.after(0, self._flush_pending)
        except Exception:
            self._flush_scheduled = False
            self.handleError(record)

    def _flush_pending(self) -> None:
        self._flush_scheduled = False
        try:
            if not getattr(self._tab, "_accept_ui_logs", True):
                self._pending.clear()
                return
            if not self._tab.frame.winfo_exists():
                self._pending.clear()
                return
        except tk.TclError:
            self._pending.clear()
            return

        n = 0
        while self._pending and n < self._BATCH:
            target, msg = self._pending.popleft()
            n += 1
            try:
                if target == "packets":
                    self._tab.append_packet_line(msg)
                else:
                    self._tab.append_app_line(msg)
            except tk.TclError:
                self._pending.clear()
                return

        if self._pending:
            self._flush_scheduled = True
            try:
                self._tab.frame.after(1, self._flush_pending)
            except tk.TclError:
                self._flush_scheduled = False
                self._pending.clear()

    def close(self) -> None:
        self._pending.clear()
        self._flush_scheduled = False
        super().close()


def attach_ui_logging(log_tab: "LogTab") -> None:
    """
    Send INFO+ app logs and DEBUG+ packet logs to the UI; leave stderr at WARNING+.
    Call once from the UI thread after LogTab exists.
    """
    import sys

    log_tab._accept_ui_logs = True

    root = logging.getLogger()
    for h in root.handlers:
        if type(h) is logging.StreamHandler and getattr(h, "stream", None) in (sys.stderr, sys.stdout):
            h.setLevel(logging.WARNING)

    logging.getLogger(PACKET_LOGGER_NAME).setLevel(logging.INFO)

    app_h = TkinterLogHandler(log_tab, target="app")
    app_h.setLevel(logging.INFO)
    app_h.addFilter(_AppLogFilter())
    root.addHandler(app_h)

    pkt_h = TkinterLogHandler(log_tab, target="packets")
    pkt_h.setLevel(logging.DEBUG)
    pkt_h.addFilter(_PacketLogFilter())
    root.addHandler(pkt_h)

    log_tab.register_handlers(app_h, pkt_h)


def detach_ui_logging(log_tab: "LogTab") -> None:
    log_tab.prepare_detach()
    for h in list(log_tab.take_handlers()):
        logging.getLogger().removeHandler(h)
        h.close()
