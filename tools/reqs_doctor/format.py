from __future__ import annotations

import re
import unicodedata
from typing import Any

_PERSIAN_DIGITS = {ord(c): ord("0") + i for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_ARABIC_DIGITS = {ord(c): ord("0") + i for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}

_FORMULA_RE = re.compile(r"^[=+\-@]")


def _sanitize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)
    normalized = normalized.replace("ي", "ی").replace("ك", "ک")
    normalized = normalized.replace("\u200c", "").replace("\u200f", "")
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch)[0] != "C")
    return normalized.strip()


def safe_comment(value: Any) -> str:
    """Return Excel-safe, Persian-normalized comment text."""

    if value is None:
        text = ""
    else:
        text = str(value)
    text = _sanitize(text)
    if _FORMULA_RE.match(text):
        text = "'" + text
    # quote sensitive tokens to avoid Excel heuristics
    if not text.startswith("\""):
        text = f'"{text}"'
    return text
