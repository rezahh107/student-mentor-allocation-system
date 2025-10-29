from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sma.export.excel_writer import EXPORT_COLUMNS, ExportWriter
from sma.phase6_import_to_sabt.exporter.csv_writer import SafeCsvWriter
from sma.phase6_import_to_sabt.models import SABT_V1_PROFILE

pytest_plugins = ["tests.fixtures.state"]


def test_always_quote_and_formula_guard(cleanup_fixtures) -> None:  # type: ignore[no-untyped-def]
    writer = SafeCsvWriter(
        header=("national_id", "counter", "notes"),
        sensitive_fields=("national_id", "counter"),
    )
    destination = cleanup_fixtures.base_dir / "safe.csv"
    rows = [
        {"national_id": "0012345678", "counter": "23373337", "notes": "=HYPERLINK(\"x\")"},
        {"national_id": "0098765432", "counter": "23373555", "notes": "normal"},
    ]
    path = writer.write(destination, rows)
    payload = path.read_bytes()
    assert payload.startswith("\ufeff".encode("utf-8")), cleanup_fixtures.context(payload=payload[:4])
    text = payload.decode("utf-8-sig")
    lines = text.split("\r\n")
    assert lines[0] == '"national_id","counter","notes"', cleanup_fixtures.context(lines=lines)
    assert '"0012345678","23373337"' in lines[1], cleanup_fixtures.context(lines=lines)
    assert "'=HYPERLINK" in lines[1], cleanup_fixtures.context(lines=lines)
    assert lines[2].startswith('"0098765432","23373555"'), cleanup_fixtures.context(lines=lines)
    leftovers = list(destination.parent.glob("*.part"))
    assert not leftovers, cleanup_fixtures.context(leftovers=[str(item) for item in leftovers])


def test_xlsx_manifest_reports_excel_safety(cleanup_fixtures) -> None:  # type: ignore[no-untyped-def]
    writer = ExportWriter(
        columns=EXPORT_COLUMNS,
        sensitive_columns=SABT_V1_PROFILE.sensitive_columns,
        include_bom=False,
    )
    row = {
        "national_id": "0012345678",
        "counter": "023731234",
        "first_name": "نام",
        "last_name": "خانواده",
        "gender": "0",
        "mobile": "09123456789",
        "reg_center": "1",
        "reg_status": "1",
        "group_code": "12",
        "student_type": "0",
        "school_code": "123456",
        "mentor_id": "M001",
        "mentor_name": "راهنما",
        "mentor_mobile": "09123456780",
        "allocation_date": datetime(2023, 3, 20, 12, 0, tzinfo=timezone.utc).isoformat(),
        "year_code": "1402",
    }
    result = writer.write_xlsx(
        [row],
        path_factory=lambda index: cleanup_fixtures.base_dir
        / f"export_{index:02d}.xlsx",
    )
    assert result.excel_safety["formula_guard"], cleanup_fixtures.context(safety=result.excel_safety)
    assert "sensitive_text_columns" in result.excel_safety, cleanup_fixtures.context(safety=result.excel_safety)
    for file in result.files:
        assert file.byte_size > 0, cleanup_fixtures.context(file=file)
        assert (cleanup_fixtures.base_dir / file.name).exists(), cleanup_fixtures.context(file=file)
    leftovers = list(cleanup_fixtures.base_dir.glob("*.part"))
    assert not leftovers, cleanup_fixtures.context(leftovers=[str(item) for item in leftovers])
