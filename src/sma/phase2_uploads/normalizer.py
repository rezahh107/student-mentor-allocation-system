from __future__ import annotations

import re
import unicodedata
from typing import Iterable

PERSIAN_Y = "ی"
ARABIC_Y = "ي"
PERSIAN_K = "ک"
ARABIC_K = "ك"

ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
CONTROL_CATEGORY = {"Cc", "Cf"}
FORMULA_PREFIX = ("=", "+", "-", "@")

DIGIT_MAP = {ord(ch): str(i) for i, ch in enumerate("۰۱۲۳۴۵۶۷۸۹")}
DIGIT_MAP.update({ord(ch): str(i) for i, ch in enumerate("٠١٢٣٤٥٦٧٨٩")})


def fold_digits(value: str | None) -> str | None:
    if value is None:
        return None
    return value.translate(DIGIT_MAP)


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = fold_digits(value) or ""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace(ARABIC_Y, PERSIAN_Y).replace(ARABIC_K, PERSIAN_K)
    value = ZERO_WIDTH_PATTERN.sub("", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) not in CONTROL_CATEGORY)
    return value.strip()


def ensure_no_formula(value: str | None) -> str | None:
    if value is None:
        return None
    for prefix in FORMULA_PREFIX:
        if value.startswith(prefix):
            raise ValueError("فرمول یا دستور مخرب شناسایی شد.")
    return value


def normalize_text_fields(fields: Iterable[str], row: dict[str, str]) -> dict[str, str]:
    updated = dict(row)
    for field in fields:
        normalized = normalize_text(updated.get(field))
        ensure_no_formula(normalized)
        updated[field] = normalized
    return updated
