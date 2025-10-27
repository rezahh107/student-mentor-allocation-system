from __future__ import annotations
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sma.phase6_import_to_sabt.data_source import InMemoryDataSource
from sma.phase6_import_to_sabt.models import (
    ExportDeltaWindow,
    ExportFilters,
    ExportSnapshot,
    NormalizedStudentRow,
)


def _row(idx: int, created_at: datetime) -> NormalizedStudentRow:
    return NormalizedStudentRow(
        national_id=f"{idx:010d}",
        counter=f"1402373{idx:04d}",
        first_name="علی",
        last_name="اکبری",
        gender=idx % 2,
        mobile="09123456789",
        reg_center=1,
        reg_status=3,
        group_code=idx % 10,
        student_type=1,
        school_code=120000 + idx,
        mentor_id=f"M{idx:05d}",
        mentor_name="راهنما",
        mentor_mobile="09120000000",
        allocation_date=created_at,
        year_code="1402",
        created_at=created_at,
        id=idx,
    )


def test_delta_windows_are_gapless() -> None:
    base = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    rows = [
        _row(1, base),
        _row(2, base),
        _row(3, base + timedelta(minutes=5)),
        _row(4, base + timedelta(minutes=5)),
    ]
    data_source = InMemoryDataSource(rows)
    snapshot = ExportSnapshot(marker="snap", created_at=base)

    all_rows = list(data_source.fetch_rows(ExportFilters(year=1402), snapshot))
    assert [row.id for row in all_rows] == [1, 2, 3, 4]

    delta = ExportDeltaWindow(created_at_watermark=rows[1].created_at, id_watermark=rows[1].id)
    delta_rows = list(data_source.fetch_rows(ExportFilters(year=1402, delta=delta), snapshot))
    assert [row.id for row in delta_rows] == [3, 4]

    data_source.rows.append(_row(5, rows[1].created_at))
    delta_rows_after_new = list(data_source.fetch_rows(ExportFilters(year=1402, delta=delta), snapshot))
    assert [row.id for row in delta_rows_after_new] == [3, 4, 5]
