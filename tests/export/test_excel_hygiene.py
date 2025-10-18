from __future__ import annotations

from repo_auditor_lite.excel_safety import render_safe_csv


def test_excel_formula_guard_and_crlf(clean_state) -> None:
    header = ("counter", "description")
    rows = [
        ("=2+2", "‌متن با اعداد۱۲۳"),
        ("@script", "  متن  "),
    ]
    content = render_safe_csv(header, rows)
    lines = content.split("\n")
    assert "'" in content.splitlines()[1]
    assert all(line.endswith("\r") for line in lines[:-1] if line)
    assert "\r\n" in content
    assert '"=2+2"' not in content
    assert "'@script" in content
