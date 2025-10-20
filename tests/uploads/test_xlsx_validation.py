import datetime as dt
from pathlib import Path

import pytest
from openpyxl import Workbook

from sma.phase6_import_to_sabt.xlsx.reader import XLSXUploadReader


@pytest.fixture
def sample_workbook(tmp_path: Path) -> Path:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Roster"
    sheet.append([
        "national_id",
        "counter",
        "first_name",
        "last_name",
        "mobile",
        "school_code",
    ])
    sheet.append([
        "۱۲۳۴۵۶۷۸۹۰",
        "۱۴۰۲۳۷۳۰۰",
        "علی\u200c",
        "کاظمی",
        "۰۹۱۲۳۴۵۶۷۸۹",
        123,
    ])
    path = tmp_path / "roster.xlsx"
    wb.save(path)
    return path


def test_schema_and_school_code_positive(sample_workbook: Path) -> None:
    reader = XLSXUploadReader()
    result = reader.read(sample_workbook)
    assert result.format == "xlsx"
    assert result.row_counts == {"Sheet_001": 1}
    row = result.rows[0].values
    assert row["national_id"] == "1234567890"
    assert row["mobile"] == "09123456789"
    assert row["school_code"] == "000123"
    assert result.excel_safety["normalized"] is True


def test_formula_guard_text_cells(tmp_path: Path) -> None:
    wb = Workbook()
    sheet = wb.active
    sheet.append(["first_name", "school_code"])
    sheet.append(["=CMD", "000001"])
    path = tmp_path / "guard.xlsx"
    wb.save(path)
    reader = XLSXUploadReader(required_columns=("school_code",))
    result = reader.read(path)
    values = result.rows[0].values
    assert values["first_name"].startswith("'")
