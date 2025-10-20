from __future__ import annotations

import csv
from datetime import datetime, timezone

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def test_handles_none_and_zero(tmp_path):
    row = make_row(idx=10, school_code=None)
    row = row.__class__(**{**row.__dict__, "mentor_id": None, "mentor_name": None, "mentor_mobile": None})
    exporter = build_exporter(tmp_path, [row])
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=ExportFilters(year=1402), options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_path = next(tmp_path.glob("*.csv"))
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        out = next(reader)
    assert out["school_code"] == ""
    assert out["mentor_id"] == ""
    assert out["student_type"] == "0"


def test_mixed_digits_and_long_names(tmp_path):
    row = make_row(idx=11)
    row = row.__class__(
        **{
            **row.__dict__,
            "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
            "first_name": "نام" * 100,
            "last_name": "خانواده" * 80,
        }
    )
    exporter = build_exporter(tmp_path, [row])
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    exporter.run(filters=ExportFilters(year=1402), options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))
    csv_path = next(tmp_path.glob("*.csv"))
    content = csv_path.read_text(encoding="utf-8")
    assert "09123456789" in content
