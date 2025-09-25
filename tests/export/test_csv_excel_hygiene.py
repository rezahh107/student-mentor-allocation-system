from pathlib import Path
from typing import Iterable

import pytest

from src.tools.export.csv_exporter import CSVAllocationExporter

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden" / "export"


@pytest.fixture
def sample_rows() -> list[dict[str, object]]:
    return [
        {
            "allocation_id": 1,
            "allocation_code": "AL-001",
            "year_code": "۱۴۰۲",
            "student_id": "۱۲۳۴۵",
            "mentor_id": 77,
            "status": "queued",
            "policy_code": "=SUM(A1:A2)",
            "created_at": "2024-01-02T03:04:05",
        },
        {
            "allocation_id": 2,
            "allocation_code": "AL-002",
            "year_code": "1402",
            "student_id": "00123",
            "mentor_id": 0,
            "status": "sent",
            "policy_code": "+HACK",
            "created_at": "",
        },
    ]


def _patch_stream(monkeypatch: pytest.MonkeyPatch, rows: Iterable[dict[str, object]]) -> None:
    def fake_stream(self: CSVAllocationExporter, *, session: object):
        return iter(rows)

    monkeypatch.setattr(CSVAllocationExporter, "_stream_rows", fake_stream, raising=False)


def test_csv_exporter_generates_bom_and_crlf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_rows: list[dict[str, object]]) -> None:
    _patch_stream(monkeypatch, sample_rows)
    exporter = CSVAllocationExporter(bom=True, crlf=True, excel_safe=True, chunk_size=1)
    output = tmp_path / "allocations_bom.csv"
    exporter.export(session=object(), output=output)
    assert output.read_bytes() == (_GOLDEN_DIR / "csv_bom_crlf.txt").read_bytes()


def test_csv_exporter_utf8_lf_without_excel_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_rows: list[dict[str, object]]) -> None:
    _patch_stream(monkeypatch, sample_rows)
    exporter = CSVAllocationExporter(bom=False, crlf=False, excel_safe=False, chunk_size=2)
    output = tmp_path / "allocations_plain.csv"
    exporter.export(session=object(), output=output)
    text = output.read_text(encoding="utf-8")
    assert text == (_GOLDEN_DIR / "csv_utf8_lf.txt").read_text(encoding="utf-8")
    assert "'=SUM" not in text
    assert "=SUM" in text
    assert "۱۴۰۲" in text
