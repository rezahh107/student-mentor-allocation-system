from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

ZERO_WIDTH_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DIGIT_MAP = str.maketrans({
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
})


def fold_digits(value: str) -> str:
    """Fold Persian/Arabic-Indic digits into Latin digits."""

    return value.translate(DIGIT_MAP)


def strip_zero_width(value: str) -> str:
    for char in ZERO_WIDTH_CHARS:
        value = value.replace(char, "")
    return value


def normalize_text(value: Optional[object]) -> str:
    """Normalize arbitrary text according to SABT domain rules."""

    if value is None:
        text = ""
    elif isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore")
    else:
        text = str(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = strip_zero_width(text)
    text = CONTROL_PATTERN.sub("", text)
    text = fold_digits(text)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return text.strip()


def normalize_phone(value: Optional[object]) -> str:
    normalized = normalize_text(value)
    digits_only = "".join(ch for ch in normalized if ch.isdigit())
    return digits_only


def sanitize_inputs(values: Iterable[Optional[object]]) -> list[str]:
    return [normalize_text(value) for value in values]


__all__ = [
    "normalize_text",
    "normalize_phone",
    "fold_digits",
    "strip_zero_width",
    "sanitize_inputs",
]
