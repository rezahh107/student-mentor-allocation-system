from __future__ import annotations

from prometheus_client import generate_latest

from phase6_import_to_sabt.models import ExportFilters, ExportOptions

from tests.export.helpers import build_job_runner, make_row


def test_export_metrics(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 4)]
    runner, metrics = build_job_runner(tmp_path, rows)
    job = runner.submit(
        filters=ExportFilters(year=1402, center=None),
        options=ExportOptions(chunk_size=2),
        idempotency_key="metrics",
        namespace="metrics",
        correlation_id="metrics",
    )
    runner.await_completion(job.id)
    output = generate_latest(metrics.registry).decode()
    assert "export_jobs_total" in output
    assert "export_rows_total" in output
