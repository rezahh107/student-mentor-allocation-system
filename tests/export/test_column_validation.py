from __future__ import annotations

import pytest
from datetime import datetime, timezone

from sma.phase6_import_to_sabt.exporter import ExportValidationError
from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from .helpers import build_exporter, make_row


def _run_export(tmp_path, row):
    exporter = build_exporter(tmp_path, [row])
    filters = ExportFilters(year=1402)
    snapshot = ExportSnapshot(marker="s", created_at=datetime(2023, 7, 1, tzinfo=timezone.utc))
    return exporter.run(filters=filters, options=ExportOptions(), snapshot=snapshot, clock_now=datetime(2023, 7, 2, tzinfo=timezone.utc))


def test_phone_regex(tmp_path):
    row = make_row(idx=1)
    row = row.__class__(**{**row.__dict__, "mobile": "0812345678"})
    with pytest.raises(ExportValidationError):
        _run_export(tmp_path, row)


def test_enums(tmp_path):
    row = make_row(idx=1)
    row = row.__class__(**{**row.__dict__, "reg_center": 9})
    with pytest.raises(ExportValidationError):
        _run_export(tmp_path, row)


def test_student_type_derived(tmp_path):
    row = make_row(idx=1, school_code=654321)
    manifest = _run_export(tmp_path, row)
    assert manifest.files[0].row_count == 1
    csv_path = next(tmp_path.glob("*.csv"))
    import csv

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        out = next(reader)
    assert out["student_type"] == "1"


def test_counter_regex(tmp_path):
    row = make_row(idx=1)
    row = row.__class__(**{**row.__dict__, "counter": "invalid"})
    with pytest.raises(ExportValidationError):
        _run_export(tmp_path, row)
