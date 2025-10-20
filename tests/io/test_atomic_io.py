from __future__ import annotations

import os
from pathlib import Path

import pytest

from sma.utils.atomic_io import atomic_write_excel_safe_csv, atomic_write_text


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_atomic_write_rollback_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "payload.txt"
    target.write_text("initial", encoding="utf-8")
    original_replace = os.replace

    def boom(_src: str | os.PathLike[str], _dst: str | os.PathLike[str]) -> None:
        raise OSError("simulate crash")

    monkeypatch.setattr("sma.utils.atomic_io.os.replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "updated")
    assert target.read_text(encoding="utf-8") == "initial"
    assert not target.with_name("payload.txt.part").exists()

    monkeypatch.setattr("sma.utils.atomic_io.os.replace", original_replace)


@pytest.mark.evidence("AGENTS.md::3 Absolute Guardrails")
def test_atomic_write_text_atomicity(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    atomic_write_text(target, "first", newline="\n")
    atomic_write_text(target, "second", newline="\n")
    assert target.read_text(encoding="utf-8") == "second"


@pytest.mark.evidence("AGENTS.md::5 Uploads & Exports (strict)")
def test_excel_safe_csv_rules(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    headers = ["national_id", "amount", "description"]
    rows = [
        {"national_id": "۰۹۱23456789", "amount": 1200, "description": "=SUM(A1:A2)"},
        {"national_id": "12345", "amount": "001", "description": "نقش@اختبار"},
    ]
    atomic_write_excel_safe_csv(path, headers, rows)
    raw_bytes = path.read_bytes()
    assert b"\r\n" in raw_bytes
    lines = raw_bytes.decode("utf-8").split("\r\n")
    assert lines[0] == "national_id,amount,description"
    assert lines[1].startswith("'09123456789")
    assert "'=SUM(A1:A2)" in lines[1]
    assert lines[2].startswith("'12345")
    assert lines[2].split(",", 2)[2] == "نقش@اختبار"
