"""BotEngine: post-kill sit guards (hostile target, recent damage)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

from engine.bot import BotEngine
from engine.combat_profile import CombatProfile
from engine.world import Npc


def _make_engine() -> BotEngine:
    gp = MagicMock()
    gp.on_server_packet = None
    gp.on_new_session = None
    return BotEngine(gp)


def test_allow_post_kill_sit_false_when_hostile_target_alive() -> None:
    be = _make_engine()
    be._combat_profile = CombatProfile(never_sit_while_target=True)
    w = be.world
    w.me.object_id = 1
    w.me.target_id = 0x200
    w.npcs[0x200] = Npc(
        object_id=0x200,
        npc_type_id=1_000_001,
        name="Goblin",
        title="",
        x=0,
        y=0,
        z=0,
        heading=0,
        is_attackable=True,
        is_dead=False,
        cur_hp_known=True,
        cur_hp=50,
        max_hp=100,
    )
    assert be._allow_post_kill_recovery_sit() is False


def test_allow_post_kill_sit_true_when_target_cleared() -> None:
    be = _make_engine()
    be._combat_profile = CombatProfile(never_sit_while_target=True)
    be.world.me.target_id = 0
    be._last_incoming_damage_mono = 0.0
    assert be._allow_post_kill_recovery_sit() is True


def test_allow_post_kill_sit_false_shortly_after_damage() -> None:
    be = _make_engine()
    be._combat_profile = CombatProfile(
        never_sit_while_target=False,
        incoming_damage_sit_block_sec=5.0,
    )
    be.world.me.target_id = 0
    be._last_incoming_damage_mono = time.monotonic()
    assert be._allow_post_kill_recovery_sit() is False


def test_buff_pause_when_in_kill_loop_and_flag_on() -> None:
    be = _make_engine()
    be._buff_profile.pause_while_auto_combat_engaged = True
    be._auto_combat = True
    be._combat_phase = "in_kill_loop"
    assert be._buff_pause_for_auto_combat() is True
