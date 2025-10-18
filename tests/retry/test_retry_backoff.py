from __future__ import annotations

from typing import List

import pytest

from repo_auditor_lite.retry import RetryExhaustedError, RetrySchedule, retry


def test_retry_schedule_deterministic() -> None:
    schedule = RetrySchedule(attempts=3, base_delay=0.1, jitter_seed="seed")
    first = schedule.delays()
    second = schedule.delays()
    assert first == second
    assert all(delay > 0 for delay in first)


def test_retry_handles_permission_error(clean_state) -> None:
    attempts: List[int] = []
    seen: List[float] = []

    def op() -> str:
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise PermissionError("busy")
        return "ok"

    def after(attempt: int, error: BaseException, delay: float) -> None:
        seen.append(round(delay, 5))

    result = retry(op, attempts=3, base_delay=0.01, jitter_seed="unit", retry_on=(PermissionError,), after_retry=after)
    assert result == "ok"
    assert len(attempts) == 3
    assert len(seen) == 2
    assert all(delay >= 0.01 for delay in seen)


def test_retry_exhaustion() -> None:
    call_count = 0

    def op() -> None:
        nonlocal call_count
        call_count += 1
        raise PermissionError("locked")

    with pytest.raises(RetryExhaustedError):
        retry(op, attempts=2, retry_on=(PermissionError,))
    assert call_count == 2
