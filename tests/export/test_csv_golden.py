from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
import codecs

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot
from phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from phase6_import_to_sabt.xlsx.retry import retry_with_backoff

from tests.export.helpers import build_exporter, make_row


def test_csv_golden_quotes_and_formula_guard(cleanup_fixtures) -> None:
    cleanup_fixtures.flush_state()
    base_one = make_row(idx=1, school_code=100001)
    base_two = make_row(idx=2, school_code=654321)
    rows = [
        base_one.__class__(
            **{
                **base_one.__dict__,
                "first_name": "=SUM(A1)",
                "last_name": "+TOTAL",
                "mentor_name": "@lookup",
                "mentor_id": "M=42",
            }
        ),
        base_two.__class__(
            **{
                **base_two.__dict__,
                "first_name": "علی",
                "last_name": "موسوی",
                "mentor_name": "-safe",
            }
        ),
    ]
    exporter = build_exporter(cleanup_fixtures.base_dir, rows)
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="golden", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    options = ExportOptions(output_format="csv", include_bom=True, excel_mode=True)
    metrics = build_import_export_metrics(cleanup_fixtures.registry)

    manifest = retry_with_backoff(
        lambda attempt: exporter.run(
            filters=filters,
            options=options,
            snapshot=snapshot,
            clock_now=snapshot.created_at,
        ),
        attempts=1,
        base_delay=0.01,
        seed="csv-golden",
        metrics=metrics,
        format_label="csv",
        sleeper=lambda _: None,
    )

    assert manifest.total_rows == 2, cleanup_fixtures.context(manifest_rows=manifest.total_rows)
    assert manifest.excel_safety.get("always_quote") is True, cleanup_fixtures.context(excel_safety=manifest.excel_safety)
    assert manifest.excel_safety.get("formula_guard") is True, cleanup_fixtures.context(excel_safety=manifest.excel_safety)
    csv_path = cleanup_fixtures.base_dir / manifest.files[0].name
    manifest_path = cleanup_fixtures.base_dir / "export_manifest.json"

    raw_bytes = csv_path.read_bytes()
    assert raw_bytes.startswith(codecs.BOM_UTF8), cleanup_fixtures.context(sample_bytes=raw_bytes[:4])
    assert b"\r\n" in raw_bytes, cleanup_fixtures.context()

    content = raw_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    header = next(reader)
    row = next(reader)
    assert header[0] == "national_id", cleanup_fixtures.context(header=header)
    assert row[2].startswith("'"), cleanup_fixtures.context(first_name=row[2])
    assert row[3].startswith("'"), cleanup_fixtures.context(last_name=row[3])
    assert row[12].startswith("'"), cleanup_fixtures.context(mentor_name=row[12])
    sensitive_snapshot = {
        "national_id": row[0],
        "counter": row[1],
        "mobile": row[5],
        "mentor_id": row[11],
        "school_code": row[10],
    }
    for column, value in sensitive_snapshot.items():
        expected = value
        assert f'"{expected}"' in content, cleanup_fixtures.context(column=column, value=value)

    csv_path.unlink()
    manifest_path.unlink()
