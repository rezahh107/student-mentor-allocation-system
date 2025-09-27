from __future__ import annotations

import csv
from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_prefix_quote(tmp_path):
    row = make_row(idx=1)
    row = row.__class__(**{**row.__dict__, "first_name": "=CMD()"})
    exporter = build_exporter(tmp_path, [row])
    filters = ExportFilters(year=1402)
    options = ExportOptions(chunk_size=10, excel_mode=True)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_path = next(tmp_path.glob("*.csv"))
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        row_out = next(reader)
    assert row_out["first_name"].startswith("'")
