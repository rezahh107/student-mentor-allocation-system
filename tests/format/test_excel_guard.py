from __future__ import annotations

from tools.reqs_doctor.format import safe_comment


def test_formula_guard():
    text = safe_comment("=SUM(۱,٢)")
    assert text == "\"'=SUM(1,2)\""
