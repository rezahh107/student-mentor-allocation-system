from __future__ import annotations

from prometheus_client import generate_latest

from sma.ops import metrics


def test_expected_metrics_present():
    metrics.reset_metrics_registry()
    counter = metrics.EXPORT_JOB_TOTAL
    counter.labels(status="completed").inc()
    metrics.EXPORT_DURATION_SECONDS.labels(phase="upload").observe(1.2)
    metrics.EXPORT_ROWS_TOTAL.labels(type="sabt").inc(100)
    metrics.EXPORT_FILE_BYTES_TOTAL.labels(kind="zip").inc(2048)
    metrics.UPLOAD_ERRORS_TOTAL.labels(type="fatal").inc()

    output = generate_latest(metrics.REGISTRY).decode()
    assert "export_jobs_total" in output
    assert "upload_errors_total" in output
