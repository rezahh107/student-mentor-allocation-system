from __future__ import annotations

from pathlib import Path

from phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic


def test_formula_injection_guard(tmp_path: Path) -> None:
    destination = tmp_path / "guard.csv"
    rows = [
        {"name": "=SUM(A1:A2)", "value": "123"},
        {"name": "+HACK", "value": "456"},
        {"name": "@cmd", "value": "789"},
        {"name": " -trim ", "value": "000"},
    ]

    write_csv_atomic(
        destination,
        rows,
        header=["name", "value"],
        sensitive_fields=["value"],
    )

    content = destination.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[1].startswith("'"), content
    assert content.count("'=") >= 1, content
    assert content.count("'+") >= 1, content
    assert content.count("'@") >= 1, content
