from __future__ import annotations

from datetime import datetime, timezone

from phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_always_quote_sensitive(tmp_path):
    rows = [make_row(idx=1)]
    exporter = build_exporter(tmp_path, rows)
    filters = ExportFilters(year=1402)
    options = ExportOptions(chunk_size=10)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=filters, options=options, snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_path = next(tmp_path.glob("*.csv"))
    content = csv_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0].startswith("\"national_id\"")
    assert lines[1].count('"') >= 2
