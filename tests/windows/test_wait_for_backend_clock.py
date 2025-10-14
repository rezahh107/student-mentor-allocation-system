"""Deterministic wait_for_backend coverage with fake clock (no real sleep)."""

from __future__ import annotations

import json
from typing import Callable, Iterator
from uuid import uuid4

import pytest

from src.ops.retry import RetryMetrics, build_retry_metrics
from src.phase6_import_to_sabt.sanitization import deterministic_jitter
from tests.fixtures.state import CleanupFixtures
from windows_launcher.launcher import LauncherError, wait_for_backend


class FakeClock:
    """Clock test double ensuring deterministic sleep without wall clock."""

    def __init__(self) -> None:
        self.timeline: list[float] = []
        self.monotonic: float = 0.0

    def sleep(self, seconds: float) -> None:
        delay = max(float(seconds), 0.0)
        self.timeline.append(delay)
        self.monotonic += delay

    def context(self) -> dict[str, object]:
        return {"timeline": list(self.timeline), "monotonic": self.monotonic}


@pytest.fixture(name="retry_metrics")
def fixture_retry_metrics(cleanup_fixtures: CleanupFixtures) -> Iterator[RetryMetrics]:
    cleanup_fixtures.flush_state()
    metrics = build_retry_metrics("wait_for_backend", cleanup_fixtures.registry)
    yield metrics
    cleanup_fixtures.flush_state()


def _probe_factory(success_at: int) -> Callable[[int, str], bool]:
    attempt_box = {"count": 0}

    def _probe(port: int, correlation_id: str) -> bool:
        del port, correlation_id
        attempt_box["count"] += 1
        return attempt_box["count"] >= success_at

    return _probe


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_wait_for_backend_uses_fake_clock(cleanup_fixtures: CleanupFixtures, retry_metrics: RetryMetrics) -> None:
    fake_clock = FakeClock()
    port = 43210
    correlation_id = uuid4().hex
    probe = _probe_factory(success_at=3)
    wait_for_backend(
        port,
        correlation_id=correlation_id,
        probe=probe,
        sleep=fake_clock.sleep,
        metrics=retry_metrics,
        max_attempts=5,
        diagnostics=lambda: "",
    )
    expected = [
        deterministic_jitter(1.0, 1, f"{port}:{correlation_id}"),
        deterministic_jitter(1.0, 2, f"{port}:{correlation_id}"),
    ]
    context = cleanup_fixtures.context(fake_clock=fake_clock.context(), expected=expected)
    assert fake_clock.timeline == pytest.approx(expected), context
    assert fake_clock.monotonic == pytest.approx(sum(expected)), context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_wait_for_backend_failure_includes_diagnostics(
    cleanup_fixtures: CleanupFixtures, retry_metrics: RetryMetrics
) -> None:
    fake_clock = FakeClock()
    port = 47890
    correlation_id = uuid4().hex
    probe = _probe_factory(success_at=999)
    diagnostics_payload = json.dumps({"stderr": "backend error"}, ensure_ascii=False)

    with pytest.raises(LauncherError) as exc_info:
        wait_for_backend(
            port,
            correlation_id=correlation_id,
            probe=probe,
            sleep=fake_clock.sleep,
            metrics=retry_metrics,
            max_attempts=3,
            diagnostics=lambda: diagnostics_payload,
        )

    error = exc_info.value
    context = cleanup_fixtures.context(fake_clock=fake_clock.context(), error=error.context)
    assert error.code == "BACKEND_UNAVAILABLE", context
    assert error.context.get("stderr_tail") == diagnostics_payload[-1024:], context
    expected_delays = [
        deterministic_jitter(1.0, 1, f"{port}:{correlation_id}"),
        deterministic_jitter(1.0, 2, f"{port}:{correlation_id}"),
    ]
    assert fake_clock.timeline == pytest.approx(expected_delays), context
