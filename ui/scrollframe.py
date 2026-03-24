"""Vertical scroll area for long tab content (Canvas + inner ttk.Frame)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ui import theme


class ScrolledFrame(ttk.Frame):
    """Fills parent; `content` is the frame to pack widgets into."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style=theme.S_FRAME)
        self._canvas = tk.Canvas(
            self,
            highlightthickness=0,
            borderwidth=0,
            bg=theme.COL_BG,
        )
        self._vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self.content = ttk.Frame(self._canvas, style=theme.S_FRAME)
        self._win = self._canvas.create_window((0, 0), window=self.content, anchor=tk.NW)

        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        for w in (self, self._canvas, self.content):
            self._bind_mousewheel(w)

    def _on_content_configure(self, _event: tk.Event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._win, width=event.width)

    def _bind_mousewheel(self, widget: tk.Misc) -> None:
        def _on_mousewheel(event: tk.Event) -> None:
            if getattr(event, "delta", 0):
                self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        widget.bind("<Enter>", lambda _e: self._canvas.bind_all("<MouseWheel>", _on_mousewheel))
        widget.bind("<Leave>", lambda _e: self._canvas.unbind_all("<MouseWheel>"))
