"""Excel-specific sanitization helpers to harden exports."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

ZERO_WIDTH_PATTERN = re.compile("[\u200b-\u200d]")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WHITESPACE_COLLAPSE = re.compile(r"\s+")
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ASCII_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MAX_CELL_LENGTH = 32767
RISKY_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def normalize_text(value: str) -> str:
    """Normalize Unicode text for Excel-safe exports."""

    normalized = unicodedata.normalize("NFC", value or "")
    normalized = normalized.replace("ي", "ی").replace("ك", "ک")
    normalized = ZERO_WIDTH_PATTERN.sub("", normalized)
    normalized = normalized.replace("\r", " ").replace("\n", " ")
    normalized = CONTROL_PATTERN.sub("", normalized)
    normalized = WHITESPACE_COLLAPSE.sub(" ", normalized)
    return normalized.strip()


def normalize_digits_ascii(value: str) -> str:
    """Fold Persian/Arabic-Indic digits to ASCII."""

    return value.translate(PERSIAN_DIGITS)


def normalize_digits_fa(value: str) -> str:
    """Fold ASCII digits to Persian for display."""

    return value.translate(ASCII_TO_PERSIAN)


def safe_cell(value: Any) -> Any:
    """Guard against Excel formula injection and enforce limits."""

    if not isinstance(value, str):
        return value
    text = value
    if text.startswith(RISKY_PREFIXES):
        text = "'" + text
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.strip()
    if len(text) > MAX_CELL_LENGTH:
        text = text[: MAX_CELL_LENGTH - 1] + "…"
    return text


__all__ = [
    "safe_cell",
    "normalize_text",
    "normalize_digits_ascii",
    "normalize_digits_fa",
]

