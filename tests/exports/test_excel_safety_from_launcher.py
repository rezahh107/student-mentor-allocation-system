from __future__ import annotations

from io import StringIO

from infrastructure.export.excel_safe import make_excel_safe_writer, sanitize_row


def test_csv_crlf_formula_guard():
    buffer = StringIO()
    writer = make_excel_safe_writer(buffer, guard_formulas=True, quote_all=True, crlf=True)
    writer.writerow(["=SUM(A1:A2)", "۰۹۱۲۳۴۵۶۷۸"])

    payload = buffer.getvalue()
    assert payload.endswith("\r\n")
    assert payload.split(",")[0].startswith('"\'=SUM')

    sanitized = sanitize_row(["=1+1", "۰۱"])
    assert sanitized[0].startswith("'")
    assert sanitized[1] == "01"
