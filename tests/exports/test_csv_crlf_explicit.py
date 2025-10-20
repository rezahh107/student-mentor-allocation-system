from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from sma.phase6_import_to_sabt.export_writer import ExportWriter
from tests.export.helpers import make_row


def test_crlf_line_terminator(tmp_path: Path) -> None:
    writer = ExportWriter(sensitive_columns=("national_id", "counter", "mobile", "mentor_id", "school_code"))
    rows = [
        replace(make_row(idx=1), mentor_name="=SUM(A1)", mentor_mobile="۰۹۱۲۳۴۵۶۷۸۹"),
        replace(make_row(idx=2), mentor_name="+A1", mentor_mobile="۰۹۱۲۳۴۵۶۷۸۰"),
    ]

    payload = [asdict(row) for row in rows]
    result = writer.write_csv(payload, path_factory=lambda index: tmp_path / f"export_{index}.csv")

    path = tmp_path / "export_1.csv"
    content = path.read_bytes()
    total_lines = len(rows) + 1
    assert content.count(b"\r\n") == total_lines, content
    assert b"\n" not in content.replace(b"\r\n", b""), content

    lines = content.decode("utf-8").split("\r\n")
    for line in [item for item in lines if item]:
        assert line.startswith('"') and line.endswith('"'), line
    assert "'=" in lines[1], lines

    assert result.excel_safety["newline"] == "\r\n"
    expected_sensitive = ["national_id", "counter", "mobile", "mentor_id", "school_code"]
    assert result.excel_safety["always_quote_columns"] == expected_sensitive
