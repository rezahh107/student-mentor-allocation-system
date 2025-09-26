from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.api.excel_io import HAS_OPENPYXL, write_csv, write_xlsx

GOLDEN_DIR = Path(__file__).resolve().parent / "golden_assets"


def _rows() -> list[list[object]]:
    return [
        ["شناسه", "۰۱۲۳۴", "=SUM(A1:A2)"],
        ["@script", "۱۲۳", datetime(2024, 1, 1, 12, 0, 0)],
        ["۰۹۱۲۳۴۵۶۷۸۹", "\u200f۰۱۲۳", "-risk"],
    ]


def test_csv_golden_roundtrip(tmp_path) -> None:
    rows = _rows()
    buffer = tmp_path / "out.csv"
    with buffer.open("wb") as handle:
        write_csv(rows, stream=handle)
    expected = (GOLDEN_DIR / "persian_roundtrip.csv").read_bytes()
    assert buffer.read_bytes() == expected


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl extra not installed")
def test_xlsx_golden_roundtrip(tmp_path) -> None:
    rows = _rows()
    payload = write_xlsx(rows, sheet_name="Students")
    import base64

    b64_path = GOLDEN_DIR / "persian_roundtrip.xlsx.b64"
    expected = base64.b64decode(b64_path.read_text())
    assert payload == expected
