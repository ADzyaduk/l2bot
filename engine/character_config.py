"""
Per-character config paths under config/characters/<slug>/.

Legacy global files config/autocombat.json and config/buffs.json are still read as
fallback when a character-specific file does not exist (migration).
"""
from __future__ import annotations

import re
from pathlib import Path

_MAX_SLUG_LEN = 80
# Logged in but name not yet known / empty — shared pre-world folder.
_OFFLINE_SLUG = "_"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def character_slug(raw_name: str | None) -> str:
    """Filesystem-safe directory name for a character; never empty."""
    if raw_name is None:
        return _OFFLINE_SLUG
    s = str(raw_name).strip()
    if not s:
        return _OFFLINE_SLUG
    for ch in '<>:"/\\|?*':
        s = s.replace(ch, "_")
    s = s.strip(" .")
    if not s:
        return _OFFLINE_SLUG
    s = re.sub(r"[\x00-\x1f]", "_", s)
    if len(s) > _MAX_SLUG_LEN:
        s = s[:_MAX_SLUG_LEN]
    if s in (".", ".."):
        return _OFFLINE_SLUG
    return s


def character_config_dir(character_name: str | None, root: Path | None = None) -> Path:
    base = root or project_root()
    return base / "config" / "characters" / character_slug(character_name)


def legacy_combat_profile_path(root: Path | None = None) -> Path:
    base = root or project_root()
    return base / "config" / "autocombat.json"


def legacy_buff_profile_path(root: Path | None = None) -> Path:
    base = root or project_root()
    return base / "config" / "buffs.json"


def character_combat_profile_path(character_name: str | None, root: Path | None = None) -> Path:
    return character_config_dir(character_name, root) / "autocombat.json"


def character_buff_profile_path(character_name: str | None, root: Path | None = None) -> Path:
    return character_config_dir(character_name, root) / "buffs.json"


def resolve_combat_profile_read_path(
    *,
    character_name: str | None,
    root: Path | None = None,
) -> tuple[Path, bool]:
    """
    Returns (path_to_read, is_character_primary).

    character_name None: legacy global only (no per-character).
    Otherwise: per-character file if it exists, else legacy if it exists,
    else per-character path (for default-new / save target hint).
    """
    r = root or project_root()
    if character_name is None:
        leg = legacy_combat_profile_path(r)
        return leg, False
    primary = character_combat_profile_path(character_name, r)
    if primary.is_file():
        return primary, True
    leg = legacy_combat_profile_path(r)
    if leg.is_file():
        return leg, False
    return primary, True


def resolve_buff_profile_read_path(
    *,
    character_name: str | None,
    root: Path | None = None,
) -> tuple[Path, bool]:
    r = root or project_root()
    if character_name is None:
        leg = legacy_buff_profile_path(r)
        return leg, False
    primary = character_buff_profile_path(character_name, r)
    if primary.is_file():
        return primary, True
    leg = legacy_buff_profile_path(r)
    if leg.is_file():
        return leg, False
    return primary, True


def resolve_combat_profile_write_path(
    *,
    character_name: str | None,
    root: Path | None = None,
) -> Path:
    r = root or project_root()
    if character_name is None:
        return legacy_combat_profile_path(r)
    return character_combat_profile_path(character_name, r)


def resolve_buff_profile_write_path(
    *,
    character_name: str | None,
    root: Path | None = None,
) -> Path:
    r = root or project_root()
    if character_name is None:
        return legacy_buff_profile_path(r)
    return character_buff_profile_path(character_name, r)
