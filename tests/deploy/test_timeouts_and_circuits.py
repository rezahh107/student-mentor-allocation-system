from __future__ import annotations

import pytest

from sma.phase7_release.deploy import CircuitBreaker, ReadinessGate


@pytest.fixture
def clean_state():
    yield


def test_breaker_open_close_cycle(clean_state):
    current = 0.0

    def clock() -> float:
        return current

    breaker = CircuitBreaker(clock=clock, failure_threshold=2, reset_timeout=5.0)

    assert breaker.allow()
    breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()

    current += 5.0
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed"


def test_readiness_timeout_error_message(clean_state):
    current = 0.0

    def clock() -> float:
        return current

    gate = ReadinessGate(clock=clock, readiness_timeout=1.0)
    with pytest.raises(RuntimeError) as exc:
        gate.assert_post_allowed(correlation_id="rid-1")
    assert "خدمت" in str(exc.value)
    current += 2.0
    with pytest.raises(RuntimeError) as exc:
        gate.assert_post_allowed(correlation_id="rid-2")
    assert "READINESS_TIMEOUT" in str(exc.value)
