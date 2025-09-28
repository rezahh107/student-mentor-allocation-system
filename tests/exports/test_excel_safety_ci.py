from __future__ import annotations

from ci_orchestrator.excel import always_quote, normalize_text, sanitize_cell


def test_formula_guard():
    assert sanitize_cell("=SUM(A1:A2)").startswith("'=")
    assert sanitize_cell("+1") == "'+1"
    assert sanitize_cell(" @foo") == "'@foo"
    assert sanitize_cell(None) == ""


def test_digit_normalization_and_trim():
    raw = "\u200c۰۱۲٣۴۵۶۷۸۹"
    assert normalize_text(raw) == "0123456789"


def test_always_quote_preserves_utf8():
    values = ["نام", "کلاس"]
    quoted = always_quote(values)
    assert quoted == ['"نام"', '"کلاس"']
