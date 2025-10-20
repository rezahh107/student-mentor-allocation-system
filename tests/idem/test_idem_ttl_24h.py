from __future__ import annotations

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions

from tests.export.helpers import build_job_runner, make_row


def test_ttl_window(tmp_path) -> None:
    rows = [make_row(idx=i) for i in range(1, 4)]
    runner, _metrics = build_job_runner(tmp_path, rows)
    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(output_format="csv")
    namespace = "ttl:test"
    idem_key = "idem-ttl"
    job = runner.submit(
        filters=filters,
        options=options,
        idempotency_key=idem_key,
        namespace=namespace,
        correlation_id="ttl-case",
    )
    redis_key = f"phase6:exports:{namespace}:{idem_key}"
    assert runner.redis.get_ttl(redis_key) == 86_400
    runner.await_completion(job.id)
