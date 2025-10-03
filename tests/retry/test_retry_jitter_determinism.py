from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from src.core.clock import Clock
from src.core.retry import RetryPolicy


@pytest.mark.parametrize(
    "attempt",
    [1, 2, 3, 4],
)
def test_b2_seeded_jitter_stable(attempt: int) -> None:
    policy = RetryPolicy(base_delay=0.25, factor=2.0, max_delay=10.0, max_attempts=5)
    delay = policy.backoff_for(attempt, correlation_id="rid-123", op="export")
    repeat_delay = policy.backoff_for(attempt, correlation_id="rid-123", op="export")
    assert delay == pytest.approx(repeat_delay), "Jitter must be deterministic"


def test_clock_timezone_is_asia_tehran() -> None:
    clock = Clock.for_timezone("Asia/Tehran")
    now = clock.now()
    assert now.tzinfo == ZoneInfo("Asia/Tehran")


def test_retry_policy_uses_clock_fixture(clock) -> None:  # type: ignore[no-untyped-def]
    frozen = Clock.for_timezone("Asia/Tehran", now_factory=clock.now)
    before = frozen.now()
    _ = frozen.isoformat()
    clock.tick(seconds=5)
    after = frozen.now()
    assert (after - before).total_seconds() == pytest.approx(5.0)
