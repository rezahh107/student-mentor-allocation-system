from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sma.phase3_allocation.outbox import BackoffPolicy
from sma.phase3_allocation.outbox.dispatcher import OutboxDispatcher
from sma.phase3_allocation.outbox.models import OutboxMessage


class _ClockStub:
    def __init__(self, mono_values: list[float], wall_values: list[datetime]) -> None:
        self._mono = iter(mono_values)
        self._wall = iter(wall_values)

    def monotonic(self) -> float:
        return next(self._mono)

    def now(self) -> datetime:
        return next(self._wall)


def test_backoff_policy_caps_delays() -> None:
    policy = BackoffPolicy(base_seconds=0.25, cap_seconds=2.0, max_retries=4)
    assert policy.next_delay(0) == pytest.approx(0.25)
    assert policy.next_delay(2) == pytest.approx(0.5)
    assert policy.next_delay(10) == pytest.approx(2.0)


def test_compute_next_available_accounts_for_skew() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    clock = _ClockStub(
        mono_values=[100.0, 100.05],
        wall_values=[base, base + timedelta(seconds=0.04)],
    )
    model = SimpleNamespace(
        event_id="evt-1",
        aggregate_id="agg-1",
        payload_json='{"idempotency_key":"abc"}',
        retry_count=1,
        status="PENDING",
        available_at=base,
        last_error=None,
        published_at=None,
    )
    message = OutboxMessage(model=model)
    policy = BackoffPolicy(base_seconds=0.5, cap_seconds=2.0, max_retries=5)

    next_available, delay, skew, remaining = message.compute_next_available_at(
        clock=clock,
        backoff=policy,
    )

    assert delay == pytest.approx(0.5)
    assert skew == pytest.approx(-0.01, rel=1e-2)
    assert remaining == pytest.approx(0.45, rel=1e-2)
    assert next_available == base + timedelta(seconds=0.49)


def test_schedule_next_marks_backoff_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    class _NoOpPublisher:
        def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
            return None

    base = datetime(2024, 5, 1, tzinfo=timezone.utc)
    model = SimpleNamespace(
        event_id="evt-2",
        aggregate_id="agg-2",
        payload_json='{"idempotency_key":"xyz"}',
        retry_count=0,
        status="PENDING",
        available_at=base,
        last_error=None,
        published_at=None,
    )
    message = OutboxMessage(model=model)
    backoff = BackoffPolicy(base_seconds=0.5, cap_seconds=1.0, max_retries=3)
    clock = SimpleNamespace(now=lambda: base, monotonic=lambda: 10.0)

    next_time = base + timedelta(seconds=2)

    def fake_compute(
        self: OutboxMessage,
        *,
        clock: object,
        backoff: BackoffPolicy,
    ) -> tuple[datetime, float, float, float]:
        return next_time, backoff.cap_seconds + 5.0, 0.2, backoff.cap_seconds

    monkeypatch.setattr(OutboxMessage, "compute_next_available_at", fake_compute, raising=True)

    dispatcher = OutboxDispatcher(
        session=SimpleNamespace(commit=lambda: None),
        publisher=_NoOpPublisher(),
        clock=clock,
        backoff=backoff,
        status_hook=lambda *args: events.append(args),
    )

    dispatcher.schedule_next(message=message, exc=RuntimeError("boom"))

    assert model.retry_count == 1
    assert model.status == "PENDING"
    assert model.available_at == next_time
    assert model.last_error.startswith("RETRYING:")
    assert events and events[-1][1] == "PENDING"
    assert events[-1][2]["code"] == "BACKOFF_CAPPED"
