"""
Bridge Python logging → Log tab (main Tk thread).

Packet traffic uses logger name "l2bot.packets" so it can be shown separately
from bot/proxy messages.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
    """Thread-safe append via Tk after()."""

    def __init__(self, log_tab: "LogTab", *, target: str) -> None:
        super().__init__()
        self._tab = log_tab
        self._target = target  # "app" | "packets"
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return

        def append() -> None:
            try:
                if self._target == "packets":
                    self._tab.append_packet_line(msg)
                else:
                    self._tab.append_app_line(msg)
            except Exception:
                pass

        try:
            self._tab.frame.after(0, append)
        except Exception:
            self.handleError(record)


def attach_ui_logging(log_tab: "LogTab") -> None:
    """
    Send INFO+ app logs and DEBUG+ packet logs to the UI; leave stderr at WARNING+.
    Call once from the UI thread after LogTab exists.
    """
    import sys

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
    for h in list(log_tab.take_handlers()):
        logging.getLogger().removeHandler(h)
        h.close()
