from __future__ import annotations

import threading
import uuid

from phase6_import_to_sabt.models import ExportFilters, ExportOptions

from tests.export.helpers import build_job_runner, make_row


def test_only_one_succeeds(tmp_path) -> None:
    rows = [make_row(idx=i) for i in range(1, 6)]
    runner, _metrics = build_job_runner(tmp_path, rows)
    filters = ExportFilters(year=1402, center=1)
    options = ExportOptions(output_format="csv")
    namespace = f"test:{uuid.uuid4().hex[:8]}"
    idem_key = f"idem-{uuid.uuid4().hex[:8]}"
    barrier = threading.Barrier(5)
    results: list[str] = []

    def _submit() -> None:
        barrier.wait()
        job = runner.submit(
            filters=filters,
            options=options,
            idempotency_key=idem_key,
            namespace=namespace,
            correlation_id=str(uuid.uuid4()),
        )
        results.append(job.id)

    threads = [threading.Thread(target=_submit) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(results)) == 1, results
    job_id = results[0]
    assert job_id in runner.jobs
    runner.await_completion(job_id)
