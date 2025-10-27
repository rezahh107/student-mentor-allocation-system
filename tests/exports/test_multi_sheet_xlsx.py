from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sma.phase6_import_to_sabt.xlsx.writer import XLSXStreamWriter


def _build_row(index: int, created_at: datetime) -> dict[str, object]:
    base_school = 100000 + (index % 500)
    return {
        "national_id": f"{index:010d}",
        "counter": f"1402373{index % 10000:04d}",
        "first_name": f"دانش‌آموز {index}",
        "last_name": "مثال",
        "gender": 0,
        "mobile": "09123456789",
        "reg_center": 1,
        "reg_status": 3,
        "group_code": index % 10,
        "student_type": 1,
        "school_code": base_school,
        "mentor_id": f"M{index:05d}",
        "mentor_name": "راهنما",
        "mentor_mobile": "09120000000",
        "allocation_date": created_at.strftime("%Y-%m-%d"),
        "year_code": "1402",
    }


def test_chunking_produces_multiple_sheets(tmp_path) -> None:
    writer = XLSXStreamWriter()
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [_build_row(i, start + timedelta(minutes=i % 5)) for i in range(60_000)]
    target = tmp_path / "export.xlsx"
    artifact = writer.write(rows, target)
    assert target.exists()
    assert sum(artifact.row_counts.values()) == len(rows)
    assert len(artifact.row_counts) == 2
    assert artifact.row_counts["Sheet_001"] == 50_000
    assert artifact.row_counts["Sheet_002"] == 10_000
    assert artifact.excel_safety["formula_guard"] is True
    assert set(artifact.excel_safety["sensitive_text"]).issuperset({"national_id", "mobile", "counter", "mentor_id", "school_code"})
