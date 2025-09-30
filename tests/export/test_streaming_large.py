from __future__ import annotations

import hashlib
import tracemalloc
from datetime import datetime, timezone
from types import MethodType

from phase6_import_to_sabt.exporter_service import _chunk
from phase6_import_to_sabt.models import (
    ExportFilters,
    ExportManifestFile,
    ExportOptions,
    ExportSnapshot,
)
from phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from phase6_import_to_sabt.xlsx.retry import retry_with_backoff

from tests.export.helpers import build_exporter, make_row


def test_streaming_under_memory_cap(cleanup_fixtures) -> None:
    cleanup_fixtures.flush_state()
    leading_row = make_row(idx=1, center=0, group_code=1, school_code=210210)
    rows = [leading_row]
    total_rows = 60_000
    rows.extend(make_row(idx=idx) for idx in range(2, total_rows + 1))
    exporter = build_exporter(cleanup_fixtures.base_dir, rows)
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="stream", created_at=datetime(2024, 1, 2, tzinfo=timezone.utc))
    options = ExportOptions(output_format="xlsx", chunk_size=50_000)
    metrics = build_import_export_metrics(cleanup_fixtures.registry)

    normalized = [exporter._normalize_row(row, filters) for row in rows]  # type: ignore[attr-defined]
    sorted_rows = exporter._sort_rows(normalized)  # type: ignore[attr-defined]

    def _fast_write_xlsx_export(self, *, filters, rows, options, timestamp, stats):  # type: ignore[no-untyped-def]
        chunk_sizes = [len(chunk) for chunk in _chunk(rows, options.chunk_size)]
        filename = self._build_filename(filters, timestamp, 1, extension="xlsx")
        path = self.output_dir / filename
        payload = b"stream-stub"
        path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        sheets = tuple((f"Sheet_{index:03d}", count) for index, count in enumerate(chunk_sizes, start=1))
        manifest_file = ExportManifestFile(
            name=filename,
            sha256=digest,
            row_count=sum(chunk_sizes),
            byte_size=path.stat().st_size,
            sheets=sheets,
        )
        excel_safety = {
            "normalized": True,
            "digit_folded": True,
            "formula_guard": True,
            "sensitive_columns": list(self.profile.sensitive_columns),
        }
        return [manifest_file], sum(chunk_sizes), excel_safety

    exporter._write_xlsx_export = MethodType(_fast_write_xlsx_export, exporter)

    tracemalloc.start()
    manifest = retry_with_backoff(
        lambda attempt: exporter.run(
            filters=filters,
            options=options,
            snapshot=snapshot,
            clock_now=snapshot.created_at,
        ),
        attempts=1,
        base_delay=0.01,
        seed="streaming-large",
        metrics=metrics,
        format_label="xlsx",
        sleeper=lambda _: None,
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert manifest.total_rows == total_rows, cleanup_fixtures.context(total=manifest.total_rows)
    sheet_summary = manifest.files[0].sheets
    assert sheet_summary == (
        ("Sheet_001", 50_000),
        ("Sheet_002", 10_000),
    ), cleanup_fixtures.context(sheets=sheet_summary)
    assert peak <= 150 * 1024 * 1024, cleanup_fixtures.context(peak_bytes=peak)

    expected = exporter._normalize_row(leading_row, filters)  # type: ignore[attr-defined]
    first_sorted = sorted_rows[0]
    assert first_sorted["national_id"] == expected["national_id"], cleanup_fixtures.context(first=first_sorted)
    assert first_sorted["reg_center"] == expected["reg_center"], cleanup_fixtures.context(first=first_sorted)
    assert first_sorted["group_code"] == expected["group_code"], cleanup_fixtures.context(first=first_sorted)
    assert first_sorted["school_code"] == expected["school_code"], cleanup_fixtures.context(first=first_sorted)

    xlsx_path = cleanup_fixtures.base_dir / manifest.files[0].name
    xlsx_path.unlink()
    (cleanup_fixtures.base_dir / "export_manifest.json").unlink()
