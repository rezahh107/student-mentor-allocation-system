from __future__ import annotations

from src.core.normalize import normalize_digits
from src.phase6_import_to_sabt.sanitization import sanitize_text


def test_nfkc_digitfold_unify() -> None:
    raw = "\u200cكلاس ۱۲۳٤"
    sanitized = sanitize_text(raw)
    digits = normalize_digits(sanitized)
    assert sanitized.startswith("کلاس")
    assert digits.endswith("1234")
