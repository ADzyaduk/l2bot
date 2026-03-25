"""Combat anchor leash and aggro retarget helpers on World."""
from __future__ import annotations

from engine.world import Npc, World


def _npc(oid: int, x: int, y: int = 0, z: int = 0) -> Npc:
    return Npc(
        object_id=oid,
        npc_type_id=oid + 1_000_000,
        name="",
        title="",
        x=x,
        y=y,
        z=z,
        heading=0,
        is_attackable=True,
    )


def test_pick_target_anchor_leash_ignores_mob_far_from_anchor() -> None:
    w = World()
    w.me.x, w.me.y, w.me.z = 2000, 0, 0
    w.npcs[1] = _npc(1, 2100, 0, 0)
    w.npcs[2] = _npc(2, 100, 0, 0)
    picked = w.pick_auto_combat_target(
        5000.0,
        prefer_aggro=False,
        retain_target_oid=0,
        retain_max_dist=0.0,
        npc_blacklist=frozenset(),
        attack_only_whitelist=False,
        npc_whitelist=frozenset(),
        target_z_range_max=0.0,
        skip_summoned=False,
        never_attack_oids=frozenset(),
        anchor_xyz=(0, 0, 0),
        anchor_leash_radius=500.0,
    )
    assert picked is not None
    assert picked.object_id == 2


def test_nearest_aggro_except_prefers_other_attacker() -> None:
    w = World()
    w.me.x, w.me.y, w.me.z = 0, 0, 0
    w.npcs[10] = _npc(10, 50, 0, 0)
    w.npcs[11] = _npc(11, 80, 0, 0)
    w.register_attacker_on_me(10)
    w.register_attacker_on_me(11)
    alt = w.nearest_aggro_npc_except(
        10,
        2000.0,
        target_z_range_max=0.0,
        npc_blacklist=frozenset(),
        attack_only_whitelist=False,
        npc_whitelist=frozenset(),
        skip_summoned=False,
        never_attack_oids=frozenset(),
        aggro_window_sec=8.0,
        anchor_xyz=None,
        anchor_leash_radius=0.0,
    )
    assert alt is not None and alt.object_id == 11


def test_any_living_attacker_threatens_me() -> None:
    w = World()
    w.npcs[99] = _npc(99, 10, 0, 0)
    w.register_attacker_on_me(99)
    assert w.any_living_attacker_threatens_me(window_sec=8.0) is True
    w.npcs.pop(99, None)
    assert w.any_living_attacker_threatens_me(window_sec=8.0) is False
