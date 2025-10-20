from datetime import datetime
from pathlib import Path
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from prometheus_client import CollectorRegistry

from sma.core.retry import (
    RetryExhaustedError,
    RetryPolicy,
    retry_attempts_total,
    retry_exhausted_total,
)
from sma.phase6_import_to_sabt.clock import FixedClock
from sma.phase6_import_to_sabt.exporter_service import ImportToSabtExporter
from sma.phase6_import_to_sabt.job_runner import DeterministicRedis, ExportJobRunner
from sma.phase6_import_to_sabt.metrics import ExporterMetrics, reset_registry
from sma.phase6_import_to_sabt.models import (
    ExportFilters,
    ExportJobStatus,
    ExportOptions,
    NormalizedStudentRow,
    SpecialSchoolsRoster,
)
from sma.phase6_import_to_sabt.roster import InMemoryRoster
from sma.utils.retry import build_retry_metrics, retry

from tests.export.helpers import make_row


@pytest.mark.evidence("AGENTS.md::6 Observability & Security")
def test_retry_metrics_namespace_records_success() -> None:
    retry_attempts_total.clear()
    retry_exhausted_total.clear()
    namespace_metrics = build_retry_metrics(namespace="unit_retry", registry=CollectorRegistry())
    call_state = {"count": 0}

    def flaky() -> str:
        call_state["count"] += 1
        if call_state["count"] == 1:
            raise ValueError("transient failure")
        return "ok"

    result = retry(
        flaky,
        attempts=3,
        base_ms=10,
        max_ms=100,
        jitter_seed="unit",
        correlation_id="unit-op",
        op="obs-success",
        metrics=namespace_metrics,
    )
    assert result == "ok"
    assert namespace_metrics.retry_attempts_total.labels(op="obs-success", outcome="retry")._value.get() == 1.0
    assert namespace_metrics.retry_attempts_total.labels(op="obs-success", outcome="success")._value.get() == 1.0
    assert namespace_metrics.retry_exhausted_total.labels(op="obs-success")._value.get() == 0.0
    assert retry_attempts_total.labels(op="obs-success", outcome="success")._value.get() >= 1.0
    assert retry_exhausted_total.labels(op="obs-success")._value.get() == 0.0


@pytest.mark.evidence("AGENTS.md::6 Observability & Security")
def test_retry_metrics_records_exhaustion() -> None:
    retry_attempts_total.clear()
    retry_exhausted_total.clear()
    namespace_metrics = build_retry_metrics(namespace="unit_retry_fail", registry=CollectorRegistry())

    def failing() -> None:
        raise RuntimeError("permanent failure")

    with pytest.raises(RetryExhaustedError):
        retry(
            failing,
            attempts=2,
            base_ms=5,
            max_ms=20,
            jitter_seed="unit-fail",
            correlation_id="cid-fail",
            op="obs-failure",
            metrics=namespace_metrics,
        )

    assert namespace_metrics.retry_exhausted_total.labels(op="obs-failure")._value.get() == 1.0
    assert retry_exhausted_total.labels(op="obs-failure")._value.get() == 1.0
    assert retry_attempts_total.labels(op="obs-failure", outcome="failure")._value.get() == 1.0


class FlakyDataSource:
    def __init__(self, rows: list[NormalizedStudentRow], failures: int) -> None:
        self._rows = rows
        self._failures = failures

    def fetch_rows(self, filters, snapshot):  # pragma: no cover - signature defined by protocol
        if self._failures > 0:
            self._failures -= 1
            raise OSError("transient fetch failure")
        for row in self._rows:
            yield row


def _build_runner(tmp_path: Path, rows: list[NormalizedStudentRow], failures: int) -> tuple[ExportJobRunner, ExporterMetrics]:
    roster: SpecialSchoolsRoster = InMemoryRoster({1402: {123456}})
    data_source = FlakyDataSource(rows, failures)
    exporter = ImportToSabtExporter(
        data_source=data_source,
        roster=roster,
        output_dir=tmp_path,
        retry_policy=RetryPolicy(max_attempts=2),
    )
    redis = DeterministicRedis()
    registry = CollectorRegistry()
    metrics = ExporterMetrics(registry)
    clock = FixedClock(datetime(2024, 1, 1, tzinfo=ZoneInfo("Asia/Tehran")))
    runner = ExportJobRunner(
        exporter=exporter,
        redis=redis,
        metrics=metrics,
        clock=clock,
        sleeper=lambda _: None,
    )
    return runner, metrics


def test_retry_and_exhaustion_counters(tmp_path) -> None:
    rows = [make_row(idx=1)]
    runner_retry, metrics_retry = _build_runner(tmp_path, rows, failures=1)
    job = runner_retry.submit(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv", chunk_size=10),
        idempotency_key="retry-once",
        namespace="retry-test",
        correlation_id="corr-retry",
    )
    runner_retry.await_completion(job.id)
    job_snapshot = runner_retry.get_job(job.id)
    assert job_snapshot is not None
    retry_samples = metrics_retry.retry_total.collect()[0].samples
    assert any(
        sample.labels.get("phase") == "query" and sample.labels.get("outcome") == "retry" and sample.value >= 1
        for sample in retry_samples
    )
    runner_retry.redis.flushdb()
    reset_registry(metrics_retry.registry)

    runner_fail, metrics_fail = _build_runner(tmp_path, rows, failures=3)
    job_fail = runner_fail.submit(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv", chunk_size=10),
        idempotency_key="retry-fail",
        namespace="retry-test",
        correlation_id="corr-fail",
    )
    runner_fail.await_completion(job_fail.id)
    job_failed = runner_fail.get_job(job_fail.id)
    assert job_failed is not None
    assert job_failed.status == ExportJobStatus.FAILED
    exhaustion_samples = metrics_fail.retry_exhaustion_total.collect()[0].samples
    assert any(sample.labels.get("phase") == "query" and sample.value >= 1 for sample in exhaustion_samples)
    runner_fail.redis.flushdb()
    reset_registry(metrics_fail.registry)

