from __future__ import annotations

import csv
from datetime import datetime, timezone

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_sort_key_is_total_order(tmp_path):
    rows = [
        make_row(idx=3, center=2, group_code=5, school_code=555555),
        make_row(idx=1, center=1, group_code=10, school_code=111111),
        make_row(idx=2, center=1, group_code=5, school_code=999999),
    ]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402)
    options = ExportOptions(chunk_size=10)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    output = next(tmp_path.glob("*.csv"))
    with open(output, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        national_ids = [row["national_id"] for row in reader]
    assert national_ids == ["0000000001", "0000000002", "0000000003"]
