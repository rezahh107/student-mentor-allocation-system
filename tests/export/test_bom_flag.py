from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_bom_on_off(tmp_path):
    rows = [make_row(idx=1)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(
        filters=filters,
        options=ExportOptions(chunk_size=10, include_bom=True),
        snapshot=snapshot,
        clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc),
    )
    csv_path = next(tmp_path.glob("*.csv"))
    data = csv_path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
