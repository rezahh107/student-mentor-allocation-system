"""Integration-grade regression tests for exporter retry/backoff and state hygiene."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Iterable
from zoneinfo import ZoneInfo

import pytest

from sma.phase6_import_to_sabt.clock import FixedClock
from sma.phase6_import_to_sabt.job_runner import ExportJobRunner
from sma.phase6_import_to_sabt.metrics import ExporterMetrics
from sma.phase6_import_to_sabt.models import (
    ExportFilters,
    ExportJobStatus,
    ExportOptions,
    ExportSnapshot,
)
from sma.phase6_import_to_sabt.sanitization import deterministic_jitter
from tests.export.helpers import build_exporter, make_row

if TYPE_CHECKING:  # pragma: no cover - typing support only
    from tests.fixtures.state import CleanupFixtures

pytest_plugins = ["tests.fixtures.state"]


@dataclass
class _FlakyExporter:
    """Proxy exporter that fails deterministically before succeeding."""

    delegate: Callable[..., object]
    failures: int
    _attempts: int = 0

    def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._attempts += 1
        if self._attempts <= self.failures:
            raise ConnectionError("redis transient outage")
        return self.delegate(*args, **kwargs)


def _build_runner(
    fixtures: "CleanupFixtures",
    *,
    rows: Iterable,
    clock: FixedClock,
    sleeper: Callable[[float], None],
    exporter_failures: int,
    max_retries: int = 4,
) -> tuple[ExportJobRunner, ExporterMetrics]:
    exporter = build_exporter(fixtures.base_dir, rows)
    flaky = _FlakyExporter(exporter.run, exporter_failures)
    metrics = ExporterMetrics(fixtures.registry)
    runner = ExportJobRunner(
        exporter=flaky,
        redis=fixtures.redis,
        metrics=metrics,
        clock=clock,
        sleeper=sleeper,
        max_retries=max_retries,
    )
    return runner, metrics


def test_export_job_runner_retry_deterministic_backoff(cleanup_fixtures: "CleanupFixtures") -> None:
    """Transient exporter errors trigger deterministic jitter without leaking state."""

    tz = ZoneInfo("Asia/Tehran")
    clock = FixedClock(datetime(2024, 3, 20, 9, 0, tzinfo=tz))
    rows = (make_row(idx=i) for i in range(1, 4))
    recorded: list[float] = []
    runner, metrics = _build_runner(
        cleanup_fixtures,
        rows=rows,
        clock=clock,
        sleeper=recorded.append,
        exporter_failures=2,
    )

    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(output_format="xlsx")
    snapshot = ExportSnapshot(marker="snap", created_at=clock.now())
    job = runner.submit(
        filters=filters,
        options=options,
        idempotency_key=f"retry-{cleanup_fixtures.namespace}",
        namespace=cleanup_fixtures.namespace,
        correlation_id=f"rid-{cleanup_fixtures.namespace}",
    )
    runner.await_completion(job.id)
    completed = runner.get_job(job.id)

    assert completed is not None and completed.status is ExportJobStatus.SUCCESS, cleanup_fixtures.context(job=completed)
    assert recorded == pytest.approx(
        [
            deterministic_jitter(0.1, 1, job.id),
            deterministic_jitter(0.1, 2, job.id),
        ]
    ), cleanup_fixtures.context(delays=recorded, job=completed)

    transient_errors = metrics.registry.get_sample_value(
        "export_errors_total",
        {"type": "transient", "format": options.output_format},
    )
    success_total = metrics.registry.get_sample_value(
        "export_jobs_total",
        {"status": ExportJobStatus.SUCCESS.value, "format": options.output_format},
    )
    assert transient_errors == pytest.approx(2.0), cleanup_fixtures.context(errors=transient_errors)
    assert success_total == pytest.approx(1.0), cleanup_fixtures.context(success=success_total)
    leftovers = list(cleanup_fixtures.base_dir.glob("**/*.part"))
    assert not leftovers, cleanup_fixtures.context(leftovers=[str(path) for path in leftovers])


def test_export_job_runner_retry_exhaustion_records_failure_metrics(
    cleanup_fixtures: "CleanupFixtures",
) -> None:
    """Retry exhaustion emits failure metrics and preserves Redis TTL deterministically."""

    tz = ZoneInfo("Asia/Tehran")
    clock = FixedClock(datetime(2024, 3, 21, 8, 30, tzinfo=tz))
    rows = (make_row(idx=i) for i in range(10, 13))
    recorded: list[float] = []
    runner, metrics = _build_runner(
        cleanup_fixtures,
        rows=rows,
        clock=clock,
        sleeper=recorded.append,
        exporter_failures=5,
        max_retries=2,
    )

    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(output_format="csv")
    snapshot = ExportSnapshot(marker="snap-fail", created_at=clock.now())
    job = runner.submit(
        filters=filters,
        options=options,
        idempotency_key=f"retry-fail-{cleanup_fixtures.namespace}",
        namespace=cleanup_fixtures.namespace,
        correlation_id=f"rid-fail-{cleanup_fixtures.namespace}",
    )
    runner.await_completion(job.id)
    failed = runner.get_job(job.id)

    assert failed is not None and failed.status is ExportJobStatus.FAILED, cleanup_fixtures.context(job=failed)
    redis_key = f"phase6:exports:{cleanup_fixtures.namespace}:retry-fail-{cleanup_fixtures.namespace}"
    assert cleanup_fixtures.redis.get_ttl(redis_key) == 86_400, cleanup_fixtures.context(redis_key=redis_key)
    assert recorded == pytest.approx([deterministic_jitter(0.1, 1, job.id)]), cleanup_fixtures.context(delays=recorded)

    failure_total = metrics.registry.get_sample_value(
        "export_jobs_total",
        {"status": ExportJobStatus.FAILED.value, "format": options.output_format},
    )
    transient_errors = metrics.registry.get_sample_value(
        "export_errors_total",
        {"type": "transient", "format": options.output_format},
    )
    payload = cleanup_fixtures.redis._hash.get(redis_key, {})  # type: ignore[attr-defined]
    assert failure_total == pytest.approx(1.0), cleanup_fixtures.context(failure=failure_total, payload=payload)
    assert transient_errors == pytest.approx(2.0), cleanup_fixtures.context(errors=transient_errors, payload=payload)
    assert "error" in payload, cleanup_fixtures.context(payload=payload)
