from __future__ import annotations

from pathlib import Path

from src.tools.export_excel_safe import export_to_path, normalize_cell


def _read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        return handle.read().splitlines()


def test_excel_safe_prefixes(tmp_path: Path) -> None:
    rows = [
        {
            "value": "=2+2",
            "plus": "+A1",
            "minus": "-3",
            "at": "@cmd",
            "tab": "\t123",
        }
    ]
    destination = tmp_path / "safe.csv"
    export_to_path(rows, headers=["value", "plus", "minus", "at", "tab"], path=destination, include_bom=False, excel_safe=True)
    data = _read_lines(destination)
    assert data[0] == '"value","plus","minus","at","tab"'
    assert data[1] == '"\'=2+2","\'+A1","\'-3","\'@cmd","\'\t123"'


def test_bom_toggle(tmp_path: Path) -> None:
    rows = [{"value": "data"}]
    with_bom = tmp_path / "bom.csv"
    export_to_path(rows, headers=["value"], path=with_bom, include_bom=True, excel_safe=True)
    without_bom = tmp_path / "nobom.csv"
    export_to_path(rows, headers=["value"], path=without_bom, include_bom=False, excel_safe=True)
    with_bom_bytes = with_bom.read_bytes()
    without_bom_bytes = without_bom.read_bytes()
    assert with_bom_bytes.startswith(b"\xef\xbb\xbf")
    assert not without_bom_bytes.startswith(b"\xef\xbb\xbf")


def test_normalization_removes_zero_width_and_digits() -> None:
    original = "۰۱۲۳٤۵‌"
    normalized = normalize_cell(original)
    assert normalized == "012345"


def test_streaming_large_dataset(tmp_path: Path) -> None:
    headers = ["value"]

    def generate() -> list[dict[str, object]]:
        for index in range(10050):
            yield {"value": f"ردیف-{index}"}

    destination = tmp_path / "large.csv"
    export_to_path(generate(), headers=headers, path=destination, include_bom=False, excel_safe=True)
    lines = _read_lines(destination)
    assert len(lines) == 10051  # header + 10050 rows
    assert lines[-1] == '"ردیف-10049"'
