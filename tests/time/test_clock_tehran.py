from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_exporter, build_job_runner, make_row


def test_clock_freeze_and_naming_determinism(tmp_path):
    tehran_now = datetime(2024, 1, 1, 8, 0, tzinfo=ZoneInfo("Asia/Tehran"))
    rows = [make_row(idx=i) for i in range(1, 3)]

    exporter = build_exporter(tmp_path, rows)
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv"),
        snapshot=ExportSnapshot(marker="snap", created_at=tehran_now),
        clock_now=tehran_now,
    )
    for file in manifest.files:
        assert "20240101080000" in file.name
    assert manifest.generated_at == tehran_now

    clock = lambda: tehran_now
    runner, metrics = build_job_runner(tmp_path / "runner", rows, clock=clock)
    job = runner.submit(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv"),
        idempotency_key="clock",
        namespace="clock",
        correlation_id="clock",
    )
    runner.await_completion(job.id)
    finished = runner.get_job(job.id)
    assert finished.manifest is not None
    assert finished.manifest.generated_at == tehran_now
