"""Excel exporter safety guarantees covering formula and atomic writes."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import csv
import pytest

from sma.phase6_import_to_sabt.export_writer import ExportWriter, atomic_writer
from tests.fixtures.state import CleanupFixtures


@pytest.fixture(name="excel_state")
def fixture_excel_state(cleanup_fixtures: CleanupFixtures) -> Iterator[CleanupFixtures]:
    cleanup_fixtures.flush_state()
    yield cleanup_fixtures
    cleanup_fixtures.flush_state()


@pytest.mark.integration
@pytest.mark.timeout(15)
def test_export_writer_guards_formulas_and_quotes(excel_state: CleanupFixtures, tmp_path: Path) -> None:
    writer = ExportWriter(sensitive_columns=("national_id", "counter"))
    rows = [
        {
            "national_id": "=123",
            "counter": "+456",
            "first_name": "علی",
            "last_name": "احمدی",
            "gender": "0",
            "mobile": "09123456789",
            "reg_center": "1",
            "reg_status": "3",
            "group_code": "10",
            "student_type": "1",
            "school_code": "123456",
            "mentor_id": "=cmd",
            "mentor_name": "مربی",
            "mentor_mobile": "09111111111",
            "allocation_date": "2024-01-01T00:00:00Z",
            "year_code": "02",
        }
    ]

    target = tmp_path / "exports" / "chunk-1.csv"
    result = writer.write_csv(rows, path_factory=lambda _: target)
    csv_path = result.files[0].path
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        row = next(reader)
    context = excel_state.context(header=header, row=row, safety=result.excel_safety)
    assert row[0].startswith("'"), context
    assert row[1].startswith("'"), context
    assert row[11].startswith("'"), context
    assert row[10].isdigit(), context
    assert result.excel_safety.get("formula_guard") is True, context
    assert "national_id" in result.excel_safety["always_quote_columns"], context


@pytest.mark.integration
@pytest.mark.timeout(10)
def test_atomic_writer_handles_crash(tmp_path: Path, excel_state: CleanupFixtures) -> None:
    target = tmp_path / "atomic" / "file.txt"
    with pytest.raises(RuntimeError):
        with atomic_writer(target) as handle:
            handle.write("partial")
            raise RuntimeError("boom")
    part_path = target.with_suffix(target.suffix + ".part")
    context = excel_state.context(target=str(target), part=str(part_path))
    assert not target.exists(), context
    assert not part_path.exists(), context

    with atomic_writer(target) as handle:
        handle.write("complete")
    context = excel_state.context(target=str(target), part=str(part_path))
    assert target.exists(), context
    assert not part_path.exists(), context
