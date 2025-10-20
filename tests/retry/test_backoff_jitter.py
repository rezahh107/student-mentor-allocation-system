from __future__ import annotations

from collections import Counter

import pytest

from sma.core.clock import tehran_clock
from sma.utils.retry import deterministic_schedule, retry


class TransientError(RuntimeError):
    pass


@pytest.mark.evidence("AGENTS.md::1 Determinism")
def test_transient_failure_eventually_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = tehran_clock()
    attempts: Counter[str] = Counter()
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        clock.now()  # touch clock to assert no wall-clock call

    def operation() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TransientError("retry me")
        return "ok"

    result = retry(
        operation,
        attempts=3,
        base_ms=100,
        max_ms=800,
        jitter_seed="imports",
        clock=clock,
        retryable=(TransientError,),
        op="transient_test",
        correlation_id="CID-1",
        sleeper=sleeper,
    )
    assert result == "ok"
    jitter_key = "imports:CID-1"
    full_schedule = deterministic_schedule(
        attempts=3,
        base_ms=100,
        max_ms=800,
        jitter_seed=jitter_key,
        op="transient_test",
    )
    assert sleeps == full_schedule[: len(sleeps)]


@pytest.mark.evidence("AGENTS.md::1 Determinism")
def test_deterministic_schedule_matches_golden() -> None:
    schedule = deterministic_schedule(
        attempts=4,
        base_ms=120,
        max_ms=1500,
        jitter_seed="shadowing",
        op="backoff_guard",
    )
    assert schedule == pytest.approx([0.12972, 0.24624, 0.5184])
