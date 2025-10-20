from __future__ import annotations

import unicodedata
from typing import Iterable

ZERO_WIDTH_CHARS = {
    "\u200c",  # ZWNJ
    "\u200d",  # ZWJ
    "\ufeff",  # BOM
}

FA_TO_EN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
AR_TO_EN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
YEH_VARIANTS = str.maketrans({"ي": "ی", "ك": "ک"})


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(FA_TO_EN_DIGITS).translate(AR_TO_EN_DIGITS)
    normalized = normalized.translate(YEH_VARIANTS)
    filtered = "".join(ch for ch in normalized if ch not in ZERO_WIDTH_CHARS and ord(ch) >= 32)
    return filtered.strip()


def sanitize_cell(value: str | None) -> str:
    if value is None:
        return ""
    text = normalize_text(str(value))
    if text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text


def always_quote(columns: Iterable[str]) -> list[str]:
    return [f'"{sanitize_cell(column)}"' for column in columns]
