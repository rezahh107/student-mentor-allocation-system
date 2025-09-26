from __future__ import annotations

import codecs
import io
from datetime import datetime, timezone

import pytest

from src.api.excel_io import (
    DEFAULT_MEMORY_LIMIT,
    ExcelMemoryError,
    ExcelRow,
    iter_csv_rows,
    sanitize_cell,
    write_csv,
)

try:  # pragma: no cover - optional dependency guard
    from src.api.excel_io import iter_xlsx_rows, write_xlsx
    OPENPYXL_AVAILABLE = True
except RuntimeError:  # raised when openpyxl missing
    OPENPYXL_AVAILABLE = False


def test_sanitize_cell_handles_persian_digits_and_injection() -> None:
    raw = "\u200c۰۱۲۳۴۵۶۷=SUM(A1)"
    sanitized = sanitize_cell(raw)
    assert sanitized == "01234567=SUM(A1)"
    assert "\u200c" not in sanitized


def test_iter_csv_rows_normalizes() -> None:
    stream = io.StringIO("۰۱۲۳,۰۹۱۲۳۴۵۶۷۸۹\n")
    rows = list(iter_csv_rows(stream))
    assert rows == [ExcelRow(cells=["0123", "09123456789"])]


def test_write_csv_emits_bom_and_masks_injection(tmp_path) -> None:
    buffer = io.BytesIO()
    write_csv([["=cmd"], ["۰۱۲۳"], ["\u200f۰۱۲۳"]], stream=buffer)
    data = buffer.getvalue()
    assert data.startswith(codecs.BOM_UTF8)
    text = data.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "'=cmd"
    assert lines[1] == "0123"
    assert lines[2] == "0123"


@pytest.mark.skipif(not OPENPYXL_AVAILABLE, reason="openpyxl extra not installed")
def test_write_xlsx_preserves_leading_zero(tmp_path) -> None:
    rows = [["۰۱۲۳", "@risk", datetime(2024, 1, 1, tzinfo=timezone.utc)], ["متن", "۱۲۳", 42]]
    payload = write_xlsx(rows, sheet_name="Students", memory_limit_bytes=DEFAULT_MEMORY_LIMIT)
    stream = io.BytesIO(payload)
    parsed = list(iter_xlsx_rows(stream, sheet="Students"))
    assert parsed[0].cells[0] == "0123"
    assert parsed[0].cells[1].startswith("'")
    assert parsed[0].cells[2].startswith("2024-")


@pytest.mark.skipif(not OPENPYXL_AVAILABLE, reason="openpyxl extra not installed")
def test_write_xlsx_memory_limit_guard() -> None:
    rows = [["الف", "ب"] for _ in range(10)]
    with pytest.raises(ExcelMemoryError):
        write_xlsx(rows, sheet_name="Students", memory_limit_bytes=10)
