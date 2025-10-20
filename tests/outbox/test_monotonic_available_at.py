from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sma.infrastructure.persistence.models import OutboxMessageModel
from sma.phase3_allocation.outbox.backoff import BackoffPolicy
from sma.phase3_allocation.outbox.models import OutboxMessage


class SkewClock:
    """Clock with controllable wall/monotonic offsets for testing."""

    def __init__(
        self,
        *,
        base_wall: datetime,
        base_monotonic: float,
        wall_offsets: list[float],
        monotonic_step: float,
    ) -> None:
        self._base_wall = base_wall
        self._base_monotonic = base_monotonic
        self._wall_offsets = wall_offsets
        self._monotonic_step = monotonic_step
        self._now_calls = 0
        self._mono_calls = 0
        self.last_now = base_wall

    def now(self) -> datetime:
        if self._now_calls < len(self._wall_offsets):
            offset = self._wall_offsets[self._now_calls]
        else:
            offset = self._wall_offsets[-1]
        self._now_calls += 1
        self.last_now = self._base_wall + timedelta(seconds=offset)
        return self.last_now

    def monotonic(self) -> float:
        value = self._base_monotonic + self._monotonic_step * self._mono_calls
        self._mono_calls += 1
        return value


@pytest.mark.parametrize("offset", (120.0, -120.0))
def test_monotonic_available_at_handles_wall_skew(offset: float) -> None:
    base_wall = datetime(2024, 1, 1, tzinfo=timezone.utc)
    clock = SkewClock(
        base_wall=base_wall,
        base_monotonic=5000.0,
        wall_offsets=[0.0, offset],
        monotonic_step=0.05,
    )
    model = OutboxMessageModel(
        id="test",
        event_id="evt",
        aggregate_type="Allocation",
        aggregate_id="1",
        event_type="MentorAssigned",
        payload_json="{}",
        occurred_at=base_wall,
        available_at=base_wall,
        retry_count=1,
        status="PENDING",
    )
    message = OutboxMessage(model=model)
    backoff = BackoffPolicy(base_seconds=1.0, cap_seconds=300.0)

    next_available, delay, skew, effective = message.compute_next_available_at(
        clock=clock,
        backoff=backoff,
    )

    assert next_available > clock.last_now
    assert pytest.approx(delay, rel=1e-6) == 1.0
    expected_remaining = 1.0 - 0.05
    assert pytest.approx(effective, rel=1e-6) == expected_remaining
    assert pytest.approx((next_available - clock.last_now).total_seconds(), rel=1e-6) == expected_remaining
    expected_skew = offset - 0.05
    assert pytest.approx(skew, rel=1e-6) == expected_skew


def test_monotonic_available_at_minimum_delay_on_negative_remaining() -> None:
    base_wall = datetime(2024, 1, 1, tzinfo=timezone.utc)
    clock = SkewClock(
        base_wall=base_wall,
        base_monotonic=100.0,
        wall_offsets=[0.0, 0.0],
        monotonic_step=2.0,
    )
    model = OutboxMessageModel(
        id="test2",
        event_id="evt2",
        aggregate_type="Allocation",
        aggregate_id="2",
        event_type="MentorAssigned",
        payload_json="{}",
        occurred_at=base_wall,
        available_at=base_wall,
        retry_count=1,
        status="PENDING",
    )
    message = OutboxMessage(model=model)
    backoff = BackoffPolicy(base_seconds=1.0, cap_seconds=300.0)

    next_available, delay, skew, effective = message.compute_next_available_at(
        clock=clock,
        backoff=backoff,
    )

    assert pytest.approx(delay, rel=1e-6) == 1.0
    assert effective == pytest.approx(backoff.base_seconds, rel=1e-6)
    assert next_available == clock.last_now + timedelta(seconds=backoff.base_seconds)
    assert skew == pytest.approx(-2.0, rel=1e-6)
