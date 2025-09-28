from __future__ import annotations

import unicodedata
from typing import Iterable

PERSIAN_YEH = "ی"
ARABIC_YEH = "ي"
PERSIAN_KEHEH = "ک"
ARABIC_KAF = "ك"
ZERO_WIDTHS = {
    "\u200c",
    "\u200d",
    "\ufeff",
    "\u200b",
}

FA_AR_DIGITS = {
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",
    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
}


def fold_digits(value: str) -> str:
    return "".join(FA_AR_DIGITS.get(ch, ch) for ch in value)


def strip_control_and_zero_width(value: str) -> str:
    return "".join(ch for ch in value if ch not in ZERO_WIDTHS and not unicodedata.category(ch).startswith("C"))


def normalize_text(value: str) -> str:
    value = fold_digits(value)
    value = value.replace(ARABIC_YEH, PERSIAN_YEH).replace(ARABIC_KAF, PERSIAN_KEHEH)
    value = strip_control_and_zero_width(value)
    value = unicodedata.normalize("NFKC", value)
    return value.strip()
