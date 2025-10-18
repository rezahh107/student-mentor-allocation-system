from __future__ import annotations

import json
from pathlib import Path

import pytest

from tooling.clock import Clock
from tooling.excel_export import ExcelSafeCSVExporter
from tooling.metrics import get_export_duration_histogram


def test_formula_guard_and_crlf_preserved(tmp_path):
    clock = Clock()
    exporter = ExcelSafeCSVExporter(clock=clock, chunk_size=500)
    rows = [
        {
            "national_id": "=1+1",
            "counter": "+SUM(A1:A2)",
            "mobile": "٠٩١٢٣٤٥٦٧٨٩",
            "text_fields_desc": "\u200cمتن",
            "year": 2024,
        },
        {
            "national_id": None,
            "counter": "-1",
            "mobile": "",
            "text_fields_desc": "ك",
            "year": 0,
        },
    ]
    columns = ["national_id", "counter", "mobile", "text_fields_desc", "year"]
    path = tmp_path / "export.csv"
    exporter.export(rows, columns, path, include_bom=True)
    data = path.read_bytes()
    assert data.startswith("\ufeff".encode("utf-8"))
    text = data.decode("utf-8-sig")
    assert "\r\n" in text
    import csv
    parsed = list(csv.reader(text.splitlines()))
    assert parsed[1][0] == "'=1+1"
    assert parsed[1][1] == "'+SUM(A1:A2)"
    assert parsed[1][2] == "09123456789"
    assert parsed[1][3] == "متن"
    assert parsed[2][3] == "ک"
    assert "373" not in text  # ensure no gender prefix leaked
    histogram = get_export_duration_histogram()
    sample = next(iter(histogram.collect())).samples[0]
    assert sample.value < 15


def test_atomic_streaming_writes(tmp_path):
    clock = Clock()
    exporter = ExcelSafeCSVExporter(clock=clock, chunk_size=1)
    rows = (
        {
            "national_id": f"00{idx:08d}",
            "counter": "0135736789",
            "mobile": "09123456789",
        }
        for idx in range(3)
    )
    path = tmp_path / "atomic.csv"
    exporter.export(rows, ["national_id", "counter", "mobile"], path)
    assert path.exists()
    assert not path.with_suffix(".csv.part").exists()
    content = path.read_bytes().decode("utf-8")
    assert content.count("\r\n") >= 4


def test_export_failure_creates_debug_artifact(tmp_path):
    clock = Clock()
    exporter = ExcelSafeCSVExporter(clock=clock, chunk_size=1)
    path = tmp_path / "failed.csv"

    def rows():
        yield {"national_id": "09123456789"}
        raise RuntimeError("09123456789 boom")

    with pytest.raises(RuntimeError):
        exporter.export(rows(), ["national_id"], path)

    debug_path = path.with_suffix(".csv.debug.json")
    payload = json.loads(debug_path.read_text(encoding="utf-8"))
    assert payload["error"].endswith("****789 boom")
    assert payload["head"][0][0] == "0912****789"


def test_sensitive_cols_always_quoted(tmp_path):
    clock = Clock()
    exporter = ExcelSafeCSVExporter(clock=clock, chunk_size=10)
    columns = ["national_id", "counter", "mobile", "mentor_id", "school_code", "notes"]
    rows = [
        {
            "national_id": "0011223344",
            "counter": "023573678",
            "mobile": "09121234567",
            "mentor_id": "=danger",
            "school_code": 42,
            "notes": "توضیح",
        },
        {
            "national_id": "",
            "counter": None,
            "mobile": "٠٩١٢٣٤٥٦٧٨٩",
            "mentor_id": "A1",
            "school_code": "٠٠١٢",  # ensure digit folding happens upstream
            "notes": "",
        },
    ]
    path = tmp_path / "quoted.csv"
    exporter.export(rows, columns, path)

    lines = [line for line in path.read_text(encoding="utf-8").split("\r\n") if line]
    data_lines = lines[1:]
    sensitive = {"national_id", "counter", "mobile", "mentor_id", "school_code"}
    for line in data_lines:
        cells = line.split(",")
        for idx, column in enumerate(columns):
            if column in sensitive:
                assert cells[idx].startswith('"') and cells[idx].endswith('"')
