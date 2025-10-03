from __future__ import annotations

from datetime import datetime, timedelta

from src.core.clock import Clock, FrozenClock, ensure_clock


def test_now_returns_tehran_aware_datetime(clock_test_context):
    active = ensure_clock(None, timezone="Asia/Tehran")
    now = active.now()
    assert now.tzinfo is not None
    assert now.tzinfo.key == "Asia/Tehran"


def test_frozen_clock_behaviour(clock_test_context):
    frozen = FrozenClock(timezone=Clock.for_tehran().timezone)
    instant = datetime(2024, 3, 20, 12, 30, tzinfo=frozen.timezone)
    frozen.set(instant)
    assert frozen.now() == instant
    before = frozen.now()
    frozen.tick(5)
    after = frozen.now()
    assert after - before == timedelta(seconds=5)
