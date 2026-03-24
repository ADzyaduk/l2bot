"""Rebuff scheduling: need_cast must not fire every tick when buff is off."""
from __future__ import annotations

from unittest.mock import MagicMock

from engine.bot import BotEngine


def test_need_cast_when_present_is_interval_only() -> None:
    be = BotEngine(MagicMock())
    assert not be._buff_need_cast(
        buff_present=True,
        now=5.0,
        last=0.0,
        interval=120.0,
        grace=False,
        party_timer_only=False,
    )
    assert be._buff_need_cast(
        buff_present=True,
        now=125.0,
        last=0.0,
        interval=120.0,
        grace=False,
        party_timer_only=False,
    )


def test_need_cast_when_absent_not_always_true_vs_interval() -> None:
    """Old bug: (not present) or interval → always True when absent."""
    be = BotEngine(MagicMock())
    assert be._buff_need_cast(
        buff_present=False,
        now=5.0,
        last=0.0,
        interval=9999.0,
        grace=False,
        party_timer_only=False,
    )
    assert be._buff_need_cast(
        buff_present=False,
        now=5.0,
        last=4.0,
        interval=9999.0,
        grace=True,
        party_timer_only=False,
    ) is False


def test_need_cast_unknown_uses_interval() -> None:
    be = BotEngine(MagicMock())
    assert not be._buff_need_cast(
        buff_present=None,
        now=5.0,
        last=1.0,
        interval=120.0,
        grace=False,
        party_timer_only=False,
    )
    assert be._buff_need_cast(
        buff_present=None,
        now=130.0,
        last=1.0,
        interval=120.0,
        grace=False,
        party_timer_only=False,
    )
