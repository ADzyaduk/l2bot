"""
Shared UI palette and ttk styles — industrial / Lineage-inspired (dark, gold + teal).
Works with plain tk + ttk; optional customtkinter windows can reuse these constants.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

COL_BG = "#0f1117"
COL_PANEL = "#161a22"
COL_RAIL = "#1e2430"
COL_ACCENT = "#d4a853"
COL_ACCENT_DIM = "#9a7a3a"
COL_TEAL = "#3ecf9b"
COL_TEXT = "#e6e2dc"
COL_MUTED = "#8a9099"
COL_WARN = "#e8b44d"
COL_LOG_BG = "#080a0e"
COL_LOG_FG = "#c5f5dc"
COL_STATUS_BG = "#121824"

FONT_TITLE = ("Trebuchet MS", 13, "bold")
FONT_SECTION = ("Trebuchet MS", 11, "bold")
FONT_UI = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)

STYLE_PREFIX = "L2"

S_FRAME = f"{STYLE_PREFIX}.TFrame"
S_LABEL = f"{STYLE_PREFIX}.TLabel"
S_LABEL_MUTED = f"{STYLE_PREFIX}Muted.TLabel"
S_TITLE = f"{STYLE_PREFIX}Title.TLabel"
S_SECTION = f"{STYLE_PREFIX}Section.TLabel"
S_NOTEBOOK = f"{STYLE_PREFIX}.TNotebook"
S_BTN = f"{STYLE_PREFIX}.TButton"
S_ENTRY = f"{STYLE_PREFIX}.TEntry"
S_CHECK = f"{STYLE_PREFIX}.TCheckbutton"
S_RADIO = f"{STYLE_PREFIX}.TRadiobutton"
S_TREE = f"{STYLE_PREFIX}.Treeview"
S_LF = f"{STYLE_PREFIX}.TLabelframe"
S_SEP = f"{STYLE_PREFIX}.TSeparator"
S_PROG = f"{STYLE_PREFIX}.Horizontal.TProgressbar"


def setup_ttk_styles(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    p = STYLE_PREFIX

    style.configure(f"{p}.TFrame", background=COL_PANEL)
    style.configure(f"{p}.TLabel", background=COL_PANEL, foreground=COL_TEXT, font=FONT_UI)
    style.configure(f"{p}Muted.TLabel", background=COL_PANEL, foreground=COL_MUTED, font=FONT_SMALL)
    style.configure(f"{p}Title.TLabel", background=COL_PANEL, foreground=COL_ACCENT, font=FONT_TITLE)
    style.configure(f"{p}Section.TLabel", background=COL_PANEL, foreground=COL_TEAL, font=FONT_SECTION)

    style.configure(f"{p}.TNotebook", background=COL_BG, borderwidth=0)
    style.configure(
        f"{p}.TNotebook.Tab",
        background=COL_RAIL,
        foreground=COL_TEXT,
        padding=[16, 8],
        font=FONT_UI,
    )
    style.map(
        f"{p}.TNotebook.Tab",
        background=[("selected", COL_PANEL), ("!selected", COL_RAIL)],
        foreground=[("selected", COL_ACCENT), ("!selected", COL_MUTED)],
    )

    style.configure(
        f"{p}.TButton",
        background=COL_RAIL,
        foreground=COL_TEXT,
        font=FONT_UI,
        padding=(10, 4),
        borderwidth=1,
        relief="flat",
    )
    # Windows + clam: incomplete maps can leave label foreground unset (invisible text).
    style.map(
        f"{p}.TButton",
        background=[
            ("disabled", COL_RAIL),
            ("pressed", COL_ACCENT_DIM),
            ("active", COL_PANEL),
        ],
        foreground=[
            ("disabled", COL_MUTED),
            ("pressed", COL_TEXT),
            ("active", COL_TEXT),
            ("!disabled", COL_TEXT),
        ],
    )

    style.configure(
        f"{p}.TCheckbutton",
        background=COL_PANEL,
        foreground=COL_TEXT,
        font=FONT_UI,
        indicatormargin=(4, 2, 10, 2),
        indicatorbackground=COL_LOG_BG,
        indicatorforeground=COL_TEXT,
    )
    style.map(
        f"{p}.TCheckbutton",
        background=[("active", COL_PANEL)],
        foreground=[
            ("disabled", COL_MUTED),
            ("selected", COL_TEXT),
            ("active", COL_TEXT),
            ("!disabled", COL_TEXT),
        ],
        indicatorcolor=[("selected", COL_TEAL), ("!selected", COL_MUTED)],
        indicatorbackground=[("active", COL_PANEL), ("!disabled", COL_LOG_BG)],
    )
    style.configure(
        f"{p}.TRadiobutton",
        background=COL_PANEL,
        foreground=COL_TEXT,
        font=FONT_UI,
        indicatormargin=(4, 2, 10, 2),
        indicatorbackground=COL_LOG_BG,
        indicatorforeground=COL_TEXT,
    )
    style.map(
        f"{p}.TRadiobutton",
        background=[("active", COL_PANEL)],
        foreground=[("disabled", COL_MUTED), ("active", COL_TEXT), ("!disabled", COL_TEXT)],
        indicatorcolor=[("selected", COL_TEAL), ("!selected", COL_MUTED)],
        indicatorbackground=[("active", COL_PANEL), ("!disabled", COL_LOG_BG)],
    )
    style.configure(f"{p}.TEntry", fieldbackground=COL_LOG_BG, foreground=COL_TEXT)
    style.configure(f"{p}.Horizontal.TProgressbar", troughcolor=COL_RAIL, background=COL_TEAL)

    style.configure(f"{p}.Treeview", background=COL_LOG_BG, foreground=COL_TEXT, fieldbackground=COL_LOG_BG, font=FONT_MONO, rowheight=22)
    style.configure(f"{p}.Treeview.Heading", background=COL_RAIL, foreground=COL_ACCENT, font=FONT_UI)
    style.map(f"{p}.Treeview", background=[("selected", COL_ACCENT_DIM)])

    style.configure(f"{p}.TLabelframe", background=COL_PANEL, foreground=COL_TEAL, font=FONT_SECTION)
    style.configure(f"{p}.TLabelframe.Label", background=COL_PANEL, foreground=COL_TEAL, font=FONT_SECTION)
    style.configure(f"{p}.TSeparator", background=COL_RAIL)

    return style
