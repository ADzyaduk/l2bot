"""
Static English names for skills and items (Interlude JSON under data/).
Optional session overlays (e.g. future ItemList names) via register_extra_*.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]
_SKILLS_JSON = _ROOT / "data" / "skills_en.json"
_ITEMS_JSON = _ROOT / "data" / "items_en.json"

_skills_cache: dict[int, str] | None = None
_items_cache: dict[int, str] | None = None
_extra_skill: dict[int, str] = {}
_extra_item: dict[int, str] = {}


def _load_map(path: Path) -> dict[int, str]:
    if not path.is_file():
        log.warning("Reference data missing: %s", path)
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {int(k): str(v) for k, v in raw.items()}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Could not load %s: %s", path, exc)
        return {}


def skill_map() -> dict[int, str]:
    global _skills_cache
    if _skills_cache is None:
        _skills_cache = _load_map(_SKILLS_JSON)
    return _skills_cache


def item_map() -> dict[int, str]:
    global _items_cache
    if _items_cache is None:
        _items_cache = _load_map(_ITEMS_JSON)
    return _items_cache


def reload_static() -> None:
    """Force re-read JSON from disk (e.g. after running fetch script)."""
    global _skills_cache, _items_cache
    _skills_cache = _load_map(_SKILLS_JSON)
    _items_cache = _load_map(_ITEMS_JSON)


def register_extra_skill_name(skill_id: int, name: str) -> None:
    """Overlay name for a skill (custom server or future live parsers)."""
    if name.strip():
        _extra_skill[skill_id] = name.strip()


def register_extra_item_name(item_id: int, name: str) -> None:
    if name.strip():
        _extra_item[item_id] = name.strip()


def clear_session_extras() -> None:
    _extra_skill.clear()
    _extra_item.clear()


def resolve_skill_name(skill_id: int) -> Optional[str]:
    if skill_id in _extra_skill:
        return _extra_skill[skill_id]
    return skill_map().get(skill_id)


def resolve_item_name(item_id: int) -> Optional[str]:
    if item_id in _extra_item:
        return _extra_item[item_id]
    return item_map().get(item_id)


def format_skill_choice(skill_id: int) -> str:
    n = resolve_skill_name(skill_id)
    if n:
        return f"{n} ({skill_id})"
    return f"Unknown skill ({skill_id})"


def format_item_choice(item_id: int) -> str:
    n = resolve_item_name(item_id)
    if n:
        return f"{n} ({item_id})"
    return f"Unknown item ({item_id})"


def search_skills(query: str, limit: int = 100) -> list[tuple[int, str]]:
    q = query.strip().lower()
    sm = skill_map()
    out: list[tuple[int, str]] = []
    if not q:
        for sid in sorted(sm.keys())[:limit]:
            out.append((sid, sm[sid]))
        return out
    for sid, name in sm.items():
        if str(sid) == q or q in name.lower():
            out.append((sid, name))
            if len(out) >= limit:
                break
    out.sort(key=lambda t: (t[1].lower(), t[0]))
    return out[:limit]


def search_items(query: str, limit: int = 100) -> list[tuple[int, str]]:
    q = query.strip().lower()
    im = item_map()
    out: list[tuple[int, str]] = []
    if not q:
        for iid in sorted(im.keys())[:limit]:
            out.append((iid, im[iid]))
        return out
    for iid, name in im.items():
        if str(iid) == q or q in name.lower():
            out.append((iid, name))
            if len(out) >= limit:
                break
    out.sort(key=lambda t: (t[1].lower(), t[0]))
    return out[:limit]
