"""Text normalization and Excel-safety helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable


_DIGIT_MAP = {ord(ch): str(idx) for idx, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_DIGIT_MAP.update({ord(ch): str(idx) for idx, ch in enumerate("٠١٢٣٤٥٦٧٨٩")})
_YEH_MAP = {ord("\u064a"): "\u06cc"}
_KEHEH_MAP = {ord("\u0643"): "\u06a9"}
_ZW_CONTROL = {ord(ch) for ch in ("\u200c", "\u200d", "\ufeff", "\u2060")}
_FORMULA_PREFIX_PATTERN = re.compile(r"^[=\-+@]")


def normalize_text(value: str) -> str:
    """Apply NFKC, digit folding, and character unification."""
    result = unicodedata.normalize("NFKC", value)
    result = result.translate(_DIGIT_MAP)
    result = result.translate(_YEH_MAP)
    result = result.translate(_KEHEH_MAP)
    result = "".join(ch for ch in result if not _is_control(ch))
    return result.strip()


def normalize_iter(values: Iterable[str]) -> list[str]:
    """Normalize an iterable of strings."""
    return [normalize_text(value) for value in values]


def ensure_excel_safe(value: str) -> str:
    """Guard against Excel formula interpretation."""
    if not value:
        return value
    guarded = value
    if _FORMULA_PREFIX_PATTERN.match(guarded):
        guarded = "'" + guarded
    return guarded


def normalize_and_guard(value: str) -> str:
    """Normalize text and apply Excel safety guard."""
    return ensure_excel_safe(normalize_text(value))


def _is_control(ch: str) -> bool:
    """Return True if char is control, zero-width, or category C."""
    if ord(ch) in _ZW_CONTROL:
        return True
    return unicodedata.category(ch).startswith("C")
