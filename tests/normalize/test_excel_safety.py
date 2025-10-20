from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

from sma.phase6_import_to_sabt.models import ExportFilters, ExportOptions, ExportSnapshot

from tests.export.helpers import build_exporter, make_row


def test_always_quote_and_formula_guard(tmp_path: Path) -> None:
    row = replace(
        make_row(idx=1),
        first_name="=HACK",
        mentor_name="+oops",
        mentor_id="@id",
        school_code=321,
    )
    exporter = build_exporter(tmp_path, [row])
    manifest = exporter.run(
        filters=ExportFilters(year=1402, center=1),
        options=ExportOptions(output_format="csv", excel_mode=True),
        snapshot=ExportSnapshot(marker="snap", created_at=row.created_at),
        clock_now=row.created_at,
    )
    csv_path = tmp_path / manifest.files[0].name
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        record = next(reader)
    assert all(cell.startswith("\"") for cell in csv_path.read_text("utf-8").splitlines()[1:])
    assert record[header.index("first_name")].startswith("'=")
    assert record[header.index("mentor_name")].startswith("'+")
    assert record[header.index("mentor_id")].startswith("'@")
    assert record[header.index("school_code")] == "000321"
    assert manifest.excel_safety["formula_guard"] is True
