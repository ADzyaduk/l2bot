"""Per-character config path helpers."""
from pathlib import Path

from engine.character_config import (
    character_buff_profile_path,
    character_combat_profile_path,
    character_slug,
    legacy_buff_profile_path,
    legacy_combat_profile_path,
    resolve_buff_profile_read_path,
    resolve_buff_profile_write_path,
    resolve_combat_profile_read_path,
    resolve_combat_profile_write_path,
)


def test_character_slug_basic() -> None:
    assert character_slug("  Foo / Bar  ") == "Foo _ Bar"
    assert character_slug("") == "_"
    assert character_slug(None) == "_"


def test_resolve_write_paths(tmp_path: Path) -> None:
    assert resolve_combat_profile_write_path(character_name=None, root=tmp_path) == (
        tmp_path / "config" / "autocombat.json"
    )
    assert resolve_buff_profile_write_path(character_name=None, root=tmp_path) == (
        tmp_path / "config" / "buffs.json"
    )
    assert resolve_combat_profile_write_path(character_name="X", root=tmp_path) == (
        tmp_path / "config" / "characters" / "X" / "autocombat.json"
    )


def test_resolve_read_fallback_to_legacy(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True)
    leg = legacy_combat_profile_path(tmp_path)
    leg.write_text("{}", encoding="utf-8")
    p, primary = resolve_combat_profile_read_path(character_name="NewChar", root=tmp_path)
    assert primary is False
    assert p == leg

    char_p = character_combat_profile_path("NewChar", tmp_path)
    char_p.parent.mkdir(parents=True, exist_ok=True)
    char_p.write_text('{"rules":[]}', encoding="utf-8")
    p2, primary2 = resolve_combat_profile_read_path(character_name="NewChar", root=tmp_path)
    assert primary2 is True
    assert p2 == char_p


def test_buff_read_fallback(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True)
    leg = legacy_buff_profile_path(tmp_path)
    leg.write_text('{"enabled": true, "rules": []}', encoding="utf-8")
    p, primary = resolve_buff_profile_read_path(character_name="Z", root=tmp_path)
    assert primary is False
    assert p == leg
