from __future__ import annotations

from phase6_import_to_sabt.models import ExportFilters, ExportOptions

from tests.export.helpers import build_job_runner, make_row


def test_parallel_post_only_one_job_succeeds(tmp_path):
    rows = [make_row(idx=1)]
    runner, _ = build_job_runner(tmp_path, rows)
    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(output_format="csv")

    first = runner.submit(
        filters=filters,
        options=options,
        idempotency_key="same",
        namespace="same",
        correlation_id="same",
    )
    second = runner.submit(
        filters=filters,
        options=options,
        idempotency_key="same",
        namespace="same",
        correlation_id="same",
    )
    assert first.id == second.id
