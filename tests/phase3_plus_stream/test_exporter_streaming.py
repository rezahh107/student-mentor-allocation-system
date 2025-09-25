import csv
import io
import tracemalloc
from typing import Iterator

import pytest

from src.tools.export_excel_safe import ExcelSafeExporter, iter_rows, normalize_cell


def test_iter_rows_normalises_persian_digits_and_formulas() -> None:
    headers = ["value"]
    rows = [
        {"value": "\u200d\u200c۱۲۳"},
        {"value": "=SUM(A1:A2)"},
        {"value": "\t456"},
        {"value": "كبير"},
    ]
    results = list(iter_rows(rows, headers=headers, excel_safe=True))
    assert results[0]["value"] == "123"
    assert results[1]["value"].startswith("'=")
    assert results[2]["value"].startswith("'\t")
    assert results[3]["value"] == "کبیر"


@pytest.mark.parametrize("total_rows", [100_000])
def test_exporter_streams_large_dataset(total_rows: int) -> None:
    headers = ["value"]
    exporter = ExcelSafeExporter(headers=headers)
    active = {"current": 0, "max": 0}

    def generate_rows() -> Iterator[dict[str, str]]:
        for index in range(total_rows):
            active["current"] += 1
            active["max"] = max(active["max"], active["current"])
            yield {"value": f"={index}"}
            active["current"] -= 1

    buffer = io.StringIO()
    tracemalloc.start()
    exporter.export(generate_rows(), buffer, include_bom=False, excel_safe=True)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert active["max"] <= 1
    # Soft assertion: ensure peak memory well below 200 MB budget.
    assert peak < 200 * 1024 * 1024
    buffer.seek(0)
    reader = csv.reader(buffer)
    header = next(reader)
    assert header == ["value"]
    first_row = next(reader)
    assert first_row[0].startswith("'=")


def test_normalize_cell_consistency() -> None:
    assert normalize_cell("\u200d\u200c0") == "0"
    assert normalize_cell(None) == ""
