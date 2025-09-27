from __future__ import annotations

from datetime import datetime, timezone, timedelta

from phase6_import_to_sabt.models import ExportDeltaWindow, ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_watermark_no_overlap(tmp_path):
    base = datetime(2023, 7, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        make_row(idx=1, created_at=base - timedelta(hours=1)),
        make_row(idx=2, created_at=base),
        make_row(idx=3, created_at=base + timedelta(hours=1)),
    ]
    exporter = build_exporter(tmp_path, rows)
    delta = ExportDeltaWindow(created_at_watermark=base, id_watermark=2)
    filters = ExportFilters(year=1402, delta=delta)
    snapshot = ExportSnapshot(marker="s", created_at=base)
    exporter.run(filters=filters, options=ExportOptions(), snapshot=snapshot, clock_now=base)
    csv_path = next(tmp_path.glob("*.csv"))
    content = csv_path.read_text(encoding="utf-8")
    assert "0000000003" in content
    assert "0000000001" not in content
    assert "0000000002" not in content
