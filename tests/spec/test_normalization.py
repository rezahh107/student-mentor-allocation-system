from __future__ import annotations

import re

from sma.phase6_import_to_sabt.exporter_service import PHONE_RE
from sma.phase6_import_to_sabt.sanitization import sanitize_phone, sanitize_text


def test_phone_nfkc_digit_folding() -> None:
    raw_phone = "۰۹\u200c۱۲۳۴\u2060۵۶۷۸۹"
    sanitized = sanitize_phone(raw_phone)
    assert sanitized == "09123456789"
    assert PHONE_RE.match(sanitized)


def test_text_unify_persian_letters() -> None:
    raw = " كيان‌ي"
    sanitized = sanitize_text(raw)
    assert sanitized == "کیانی"
    assert not re.search(r"[\u200c\u200d]", sanitized)

