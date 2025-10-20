from __future__ import annotations

import csv
from pathlib import Path

from sma.export.excel_writer import ExportWriter


def _read_csv(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return [row for row in reader]


def test_formula_guard_and_crlf_preserved(tmp_path: Path) -> None:
    writer = ExportWriter(sensitive_columns=["national_id", "counter", "mobile"], include_bom=False)
    dangerous = {
        "national_id": "=1+2",
        "counter": "+123",
        "first_name": "یاسمن",
        "last_name": "كاظمی",
        "gender": "1",
        "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
        "reg_center": "2",
        "reg_status": "3",
        "group_code": "200",
        "student_type": "1",
        "school_code": "123",
        "mentor_id": "009",
        "mentor_name": "=cmd|'/C calc'!A0",
        "mentor_mobile": "00912345678",
        "allocation_date": "2024-01-01T00:00:00Z",
        "year_code": "۱۴۰۲",
    }
    result = writer.write_csv([dangerous], path_factory=lambda _: tmp_path / "export.csv")
    csv_path = tmp_path / "export.csv"
    assert csv_path.exists()
    assert not (tmp_path / "export.csv.part").exists()
    payload_bytes = csv_path.read_bytes()
    assert b"\r\n" in payload_bytes, f"Context: no CRLF detected -> {payload_bytes!r}"
    without_crlf = payload_bytes.replace(b"\r\n", b"")
    assert b"\n" not in without_crlf, f"Context: stray LF detected -> {payload_bytes!r}"
    rows = _read_csv(csv_path)
    assert rows[0][0] == "national_id", f"Context: header row mismatch -> {rows}"
    assert rows[1][0].startswith("'="), f"Context: formula guard missing -> {rows[1]}"
    assert rows[1][1].startswith("'+"), f"Context: numeric guard missing -> {rows[1]}"
    assert rows[1][5] == "09123456789", f"Context: digit folding failed -> {rows[1]}"
    assert rows[1][15] == "1402", f"Context: normalization failed -> {rows[1]}"
    raw_row = payload_bytes.split(b"\r\n")[1]
    assert all(
        part.startswith(b'"') and part.endswith(b'"') for part in raw_row.split(b",")
    ), f"Context: quoting failure -> {raw_row!r}"
    assert result.total_rows == 1, f"Context: incorrect row count -> {result}"
    assert result.excel_safety["formula_guard"] is True
    assert result.excel_safety["always_quote"] is True

