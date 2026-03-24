"""World: reject bogus StatusUpdate max HP/MP for self; hp_pct_safe uses baseline."""
from __future__ import annotations

from core.packets.server import (
    ATTR_CUR_HP,
    ATTR_MAX_HP,
    ATTR_CUR_MP,
    ATTR_MAX_MP,
    StatusUpdate,
    UserInfo,
)
from engine.world import World


def _user_info(oid: int, cur_hp: int, max_hp: int, cur_mp: int, max_mp: int) -> UserInfo:
    return UserInfo(
        object_id=oid,
        cur_hp=cur_hp,
        max_hp=max_hp,
        cur_mp=cur_mp,
        max_mp=max_mp,
        name="Test",
    )


def test_status_update_rejects_small_max_hp_keeps_baseline() -> None:
    w = World()
    oid = 0x100
    w.on_user_info(_user_info(oid, cur_hp=200, max_hp=249, cur_mp=100, max_mp=120))

    bad = StatusUpdate(object_id=oid, attrs={ATTR_CUR_HP: 106, ATTR_MAX_HP: 12})
    w.on_status_update(bad)

    assert w.me.max_hp == 249
    assert w.me.max_hp_baseline == 249
    assert w.me.hp_pct_safe <= 100.0
    assert abs(w.me.hp_pct_safe - (106 / 249 * 100)) < 0.01
    assert abs(w.me.hp_pct - w.me.hp_pct_safe) < 0.01


def test_effective_max_ignores_corrupt_max_smaller_than_baseline() -> None:
    """If max_hp field is corrupted but baseline exists, HP% must not use raw max (e.g. 106/12)."""
    w = World()
    oid = 0x200
    w.on_user_info(_user_info(oid, cur_hp=106, max_hp=249, cur_mp=50, max_mp=97))
    w.me.max_hp = 12
    assert w.me.effective_max_hp() == 249
    assert w.me.hp_pct <= 100.0
    assert abs(w.me.hp_pct - (106 / 249 * 100)) < 0.01


def test_status_update_accepts_consistent_max_hp() -> None:
    w = World()
    oid = 7
    w.on_user_info(_user_info(oid, 50, 100, 10, 40))

    ok = StatusUpdate(object_id=oid, attrs={ATTR_CUR_HP: 80, ATTR_MAX_HP: 200})
    w.on_status_update(ok)

    assert w.me.cur_hp == 80
    assert w.me.max_hp == 200


def test_mp_sanity_rejects_max_below_cur() -> None:
    w = World()
    oid = 3
    w.on_user_info(_user_info(oid, 10, 50, 30, 80))

    bad = StatusUpdate(object_id=oid, attrs={ATTR_CUR_MP: 40, ATTR_MAX_MP: 5})
    w.on_status_update(bad)

    assert w.me.max_mp == 80
    assert w.me.mp_pct_safe <= 100.0
