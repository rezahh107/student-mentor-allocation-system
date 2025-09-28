from __future__ import annotations

import codecs
from io import StringIO

from ci_orchestrator.excel import always_quote, normalize_text, sanitize_cell


def test_quotes_formula_guard_crlf_bom(tmp_path) -> None:
    assert sanitize_cell("=SUM(A1:A2)").startswith("'=")
    assert sanitize_cell("@cmd").startswith("'@")
    assert normalize_text("\ufeff۰۱۲۳۴۵۶۷۸۹\u200c ") == "0123456789"

    quoted = always_quote(["کلاس", "Name"])
    assert quoted == ['"کلاس"', '"Name"']

    buffer = StringIO()
    buffer.write("\ufeff\"value\"\r\n")
    payload = buffer.getvalue().encode("utf-8")
    assert payload.startswith(codecs.BOM_UTF8)
