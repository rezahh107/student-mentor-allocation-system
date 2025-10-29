from __future__ import annotations

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from prometheus_client import CollectorRegistry

from sma.phase6_import_to_sabt.clock import FixedClock
from sma.phase6_import_to_sabt.export_runner import RetryingExportRunner
from sma.phase6_import_to_sabt.metrics import ExporterMetrics

pytest_plugins = ["tests.fixtures.state"]


def _expected_delays(base_delay: float, correlation_id: str, attempts: int) -> list[float]:
    values: list[float] = []
    for attempt in range(1, attempts):
        digest = hashlib.blake2b(f"{correlation_id}:{attempt}".encode("utf-8"), digest_size=8).digest()
        jitter = int.from_bytes(digest, "big") / 2**64
        factor = 1 + (jitter * 0.1)
        values.append(base_delay * (2 ** (attempt - 1)) * factor)
    return values


def test_deterministic_jitter_schedule(cleanup_fixtures) -> None:  # type: ignore[no-untyped-def]
    tz = ZoneInfo("Asia/Tehran")
    clock = FixedClock(datetime(2024, 3, 20, 8, 0, tzinfo=tz))
    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry)
    recorded: list[float] = []
    runner = RetryingExportRunner(
        retryable=(TimeoutError,),
        clock=clock,
        sleeper=recorded.append,
        metrics=metrics,
        base_delay=0.2,
        max_attempts=4,
    )
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 4:
            raise TimeoutError("redis flake")
        return "ok"

    result = runner.execute(flaky, reason="query", correlation_id=cleanup_fixtures.namespace)
    assert result == "ok", cleanup_fixtures.context(result=result, delays=recorded)
    assert recorded == pytest.approx(
        _expected_delays(0.2, cleanup_fixtures.namespace, 4)
    ), cleanup_fixtures.context(delays=recorded)

    attempts_metric = registry.get_sample_value(
        "export_retry_attempts_total",
        {"reason": "query:TimeoutError"},
    )
    exhausted_metric = registry.get_sample_value(
        "export_retries_exhausted_total",
        {"reason": "query:TimeoutError"},
    )
    assert attempts_metric == pytest.approx(3.0), cleanup_fixtures.context(attempts=attempts_metric)
    assert exhausted_metric in (None, 0.0), cleanup_fixtures.context(exhausted=exhausted_metric)
