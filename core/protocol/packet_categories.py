"""
Heuristic S2C categories for log tagging (skill / item related names from registry).
Teon uses XOR; many lines stay Unknown_* — tags apply when the name matches.
"""
from __future__ import annotations

_SKILL_TOKENS = (
    "SKILL",
    "MAGIC",
    "ABNORMAL",
    "COOL",
    "BUFF",
    "CAST",
    "TOGGLE",
)
_ITEM_TOKENS = (
    "ITEM",
    "INVENTORY",
    "PICKUP",
    "DROP",
    "WAREHOUSE",
    "SPOIL",
    "ENCHANT",
    "SOULSHOT",
)


def s2c_category_tag(packet_name: str) -> str:
    """Return short tag for log prefix, or empty string."""
    u = packet_name.upper()
    for t in _SKILL_TOKENS:
        if t in u:
            return "skill"
    for t in _ITEM_TOKENS:
        if t in u:
            return "item"
    return ""
