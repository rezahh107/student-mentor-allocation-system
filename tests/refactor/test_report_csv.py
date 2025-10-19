from __future__ import annotations

from pathlib import Path

from tools.refactor_imports import ModuleFix, write_report_csv


def test_formula_guard_and_crlf(tmp_path: Path, clean_state) -> None:
    target = tmp_path / "report.csv"
    fixes = [
        ModuleFix(
            file_path=tmp_path / "example.py",
            action="import_rewrite",
            original="=phase",
            updated="src.phase1",
        )
    ]
    write_report_csv(target, fixes)
    payload = target.read_bytes()
    assert payload.startswith(b'"file","action","original","updated"')
    assert b"\r\n" in payload
    assert b"'=phase" in payload
