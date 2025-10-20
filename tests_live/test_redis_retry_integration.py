"""Opt-in live Redis retry integration checks."""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import pytest
from prometheus_client import CollectorRegistry

try:  # pragma: no cover - optional dependency for local CI
    from redis import Redis
except Exception as exc:  # pragma: no cover - redis might be unavailable locally
    Redis = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from sma.phase6_import_to_sabt.sanitization import deterministic_jitter
from sma.phase6_import_to_sabt.xlsx.job_store import RedisExportJobStore
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from tests.retry.test_datastore_retry_metrics import (
    SequenceTimer,
    _collect_counter_samples,
    _collect_hist_summaries,
)

LIVE_REDIS_URL = os.getenv("LIVE_REDIS_URL")

if LIVE_REDIS_URL is None or LIVE_REDIS_URL.strip() == "":  # pragma: no cover - opt-in guard
    pytest.skip("LIVE_REDIS_URL is not configured; skipping live Redis suite.", allow_module_level=True)

if Redis is None:  # pragma: no cover - dependency missing in some environments
    pytest.skip(f"redis library missing: {_IMPORT_ERROR}", allow_module_level=True)


@pytest.fixture(name="live_redis")
def fixture_live_redis() -> Iterator[Redis]:  # type: ignore[no-untyped-def]
    client = Redis.from_url(LIVE_REDIS_URL, decode_responses=True)
    client.ping()
    yield client
    client.close()


@pytest.mark.retry_logic
@pytest.mark.integration
def test_live_redis_transient_failures_expose_metrics(live_redis: Redis) -> None:  # type: ignore[no-untyped-def]
    namespace = f"live-redis:{uuid.uuid4().hex}"
    pattern = f"{namespace}:*"

    def _cleanup() -> None:
        for key in live_redis.scan_iter(match=pattern):
            live_redis.delete(key)

    _cleanup()

    registry = CollectorRegistry()
    metrics = build_import_export_metrics(registry=registry)
    metrics.reset()

    timer = SequenceTimer(iter([0.0, 0.004, 0.01, 0.016, 0.022, 0.028, 0.034]))
    backoff_delays: list[float] = []
    attempts = {"hset": 0, "hgetall": 0}

    original_hset = live_redis.hset
    original_hgetall = live_redis.hgetall

    def flaky_hset(key: str, mapping: dict[str, str]) -> None:
        if key.startswith(f"{namespace}:export:") and attempts["hset"] == 0:
            attempts["hset"] += 1
            raise ConnectionError("transient-hset")
        original_hset(key, mapping)

    def flaky_hgetall(key: str) -> dict[str, str]:
        if key.startswith(f"{namespace}:export:") and attempts["hgetall"] == 0:
            attempts["hgetall"] += 1
            raise ConnectionError("transient-hgetall")
        return original_hgetall(key)

    live_redis.hset = flaky_hset  # type: ignore[assignment]
    live_redis.hgetall = flaky_hgetall  # type: ignore[assignment]

    store = RedisExportJobStore(
        redis=live_redis,
        namespace=namespace,
        now=lambda: "2024-01-01T00:00:00+03:30",
        metrics=metrics,
        sleeper=lambda seconds: backoff_delays.append(seconds),
        timer=timer,
    )

    try:
        payload = store.begin("job-live", file_format="csv", filters={"center": 7})
        assert payload["status"] == "PENDING", {
            "context": "begin-payload",
            "payload": payload,
            "namespace": namespace,
        }

        loaded = store.load("job-live")
        assert loaded is not None, {
            "context": "load-result",
            "namespace": namespace,
            "keys": list(live_redis.scan_iter(match=pattern)),
        }

        attempt_samples = _collect_counter_samples(metrics.retry_total)
        exhaustion_samples = _collect_counter_samples(metrics.retry_exhausted_total)
        backoff_sums, backoff_counts = _collect_hist_summaries(metrics.retry_backoff_seconds)
        duration_sums, duration_counts = _collect_hist_summaries(metrics.retry_duration_seconds)

        expected_begin_backoff = deterministic_jitter(store.base_delay, 1, "redis_begin")
        expected_read_backoff = deterministic_jitter(store.base_delay, 1, "redis_read")

        assert backoff_delays == pytest.approx([expected_begin_backoff, expected_read_backoff]), {
            "context": "backoff-delays",
            "captured": backoff_delays,
            "expected": [expected_begin_backoff, expected_read_backoff],
        }

        assert attempt_samples.get(("redis_begin", "n/a"), 0.0) == pytest.approx(1.0), {
            "context": "retry-attempts",
            "samples": attempt_samples,
        }
        assert attempt_samples.get(("redis_read", "n/a"), 0.0) == pytest.approx(1.0), {
            "context": "retry-attempts",
            "samples": attempt_samples,
        }
        assert exhaustion_samples.get(("redis_begin", "n/a"), 0.0) == 0.0, {
            "context": "exhaustion",
            "samples": exhaustion_samples,
        }
        assert exhaustion_samples.get(("redis_read", "n/a"), 0.0) == 0.0, {
            "context": "exhaustion",
            "samples": exhaustion_samples,
        }

        assert backoff_counts.get(("redis_begin", "n/a"), 0.0) == pytest.approx(1.0), {
            "context": "backoff-begin",
            "counts": backoff_counts,
        }
        assert backoff_counts.get(("redis_read", "n/a"), 0.0) == pytest.approx(1.0), {
            "context": "backoff-read",
            "counts": backoff_counts,
        }
        assert backoff_sums.get(("redis_begin", "n/a"), 0.0) == pytest.approx(expected_begin_backoff), {
            "context": "backoff-sum-begin",
            "sums": backoff_sums,
        }
        assert backoff_sums.get(("redis_read", "n/a"), 0.0) == pytest.approx(expected_read_backoff), {
            "context": "backoff-sum-read",
            "sums": backoff_sums,
        }

        assert duration_counts.get(("redis_begin", "n/a"), 0.0) == pytest.approx(2.0), {
            "context": "duration-count-begin",
            "counts": duration_counts,
        }
        assert duration_counts.get(("redis_read", "n/a"), 0.0) == pytest.approx(2.0), {
            "context": "duration-count-read",
            "counts": duration_counts,
        }
        assert duration_sums.get(("redis_begin", "n/a"), 0.0) == pytest.approx(0.008, abs=1e-6), {
            "context": "duration-sum-begin",
            "sums": duration_sums,
        }
        assert duration_sums.get(("redis_read", "n/a"), 0.0) == pytest.approx(0.008, abs=1e-6), {
            "context": "duration-sum-read",
            "sums": duration_sums,
        }

    finally:
        live_redis.hset = original_hset  # type: ignore[assignment]
        live_redis.hgetall = original_hgetall  # type: ignore[assignment]
        _cleanup()
