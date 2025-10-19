from __future__ import annotations

from pathlib import Path

from tools.refactor_imports import ModuleFix, normalize_persian_value, write_report_csv


def test_digit_folding_nfkc_formula_guard_crlf(tmp_path: Path) -> None:
    fixes = [
        ModuleFix(
            file_path=tmp_path / "نمونه.py",
            action="اصلاح",
            original="۰۱۲۳۴",
            updated="=SUM(A1:A2)",
        )
    ]
    csv_path = tmp_path / "report.csv"
    write_report_csv(csv_path, fixes)
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        content = handle.read()
    assert content.endswith("\r\n")
    assert "'" in content  # formula guard
    assert "01234" in content
    assert normalize_persian_value("٠۱۲۳٤") == "01234"
