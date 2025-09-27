from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_chunk_boundaries(tmp_path):
    rows = [make_row(idx=i) for i in range(1, 7)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402)
    options = ExportOptions(chunk_size=2)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_files = sorted(tmp_path.glob("*.csv"))
    assert len(csv_files) == 3
    sizes = [path.stat().st_size for path in csv_files]
    assert sizes[0] > 0 and sizes[1] > 0 and sizes[2] > 0
