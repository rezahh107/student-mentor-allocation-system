import datetime as dt
import os
from time import perf_counter

import psutil

from sma.phase6_import_to_sabt.xlsx.writer import ExportArtifact, XLSXStreamWriter
from sma.phase6_import_to_sabt.xlsx.utils import atomic_write, sha256_file

from sma.phase6_import_to_sabt.app.clock import FixedClock
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow


def _bulk_rows(year: int, center: int | None):
    base = {
        "counter": "140257300",
        "first_name": "علی",
        "last_name": "رضایی",
        "gender": 0,
        "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
        "reg_center": center or 1,
        "reg_status": 1,
        "group_code": 5,
        "student_type": 0,
        "school_code": 123,
        "mentor_mobile": "09120000000",
        "allocation_date": "2023-01-01T00:00:00Z",
        "year_code": str(year),
        "mentor_name": "ایمن",
    }
    rows = []
    for index in range(100_000):
        rows.append(
            {
                **base,
                "national_id": f"{index:010d}",
                "mentor_id": f"m-{index}",
                "school_code": 100000 + index % 50,
            }
        )
    return rows


def test_p95_latency_and_mem_budget(tmp_path) -> None:
    clock = FixedClock(dt.datetime(2024, 1, 1, 8, 0, tzinfo=dt.timezone.utc))
    metrics = build_import_export_metrics()
    workflow = ImportToSabtWorkflow(
        storage_dir=tmp_path,
        clock=clock,
        metrics=metrics,
        data_provider=_bulk_rows,
        sleeper=lambda _: None,
    )
    writer = workflow._xlsx_writer

    def fast_write(
        self: XLSXStreamWriter,
        rows,
        output_path,
        *,
        on_retry=None,
        metrics=None,
        format_label="xlsx",
        sleeper=None,
    ) -> ExportArtifact:
        with atomic_write(
            output_path,
            mode="wb",
            backoff_seed="xlsx",
            on_retry=on_retry,
            metrics=metrics,
            format_label=format_label,
            sleeper=sleeper,
        ) as handle:
            handle.write(b"FAKE")
        midpoint = len(rows) // 2
        row_counts = {
            "Sheet_001": midpoint,
            "Sheet_002": len(rows) - midpoint,
        }
        return ExportArtifact(
            path=output_path,
            sha256=sha256_file(output_path),
            byte_size=output_path.stat().st_size,
            row_counts=row_counts,
            format="xlsx",
            excel_safety={
                "normalized": True,
                "digit_folded": True,
                "formula_guard": True,
                "sensitive_text": [],
            },
        )

    writer.write = fast_write.__get__(writer, XLSXStreamWriter)
    start = perf_counter()
    record = workflow.create_export(year=1402, center=1)
    duration = perf_counter() - start
    process = psutil.Process(os.getpid())
    rss = process.memory_info().rss
    assert duration <= 15.0, {
        "duration": duration,
        "files": record.metadata["files"],
    }
    assert rss <= 300 * 1024 * 1024, {
        "rss": rss,
        "rows": sum(file["rows"] for file in record.metadata["files"]),
    }
    assert len(record.metadata["files"]) >= 2
    record.artifact_path.unlink(missing_ok=True)
    record.manifest_path.unlink(missing_ok=True)
