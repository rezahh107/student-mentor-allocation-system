# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

PERSIAN_DIGIT_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
YEH_KEHEH_MAP = str.maketrans({"ي": "ی", "ك": "ک"})
ZERO_WIDTH = {"\u200c", "\u200d", "\u200b", "\ufeff"}
MOBILE_PATTERN = re.compile(r"^09\d{9}$")


@dataclass(frozen=True, slots=True)
class MobileValidationError(ValueError):
    message_fa: str

    def __str__(self) -> str:  # pragma: no cover - simple proxy
        return self.message_fa


def _strip_control_chars(value: str) -> str:
    return "".join(
        ch
        for ch in value
        if ch not in ZERO_WIDTH and unicodedata.category(ch)[0] != "C"
    )


def normalize_mobile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(YEH_KEHEH_MAP)
    normalized = normalized.translate(PERSIAN_DIGIT_FOLD)
    normalized = _strip_control_chars(normalized)
    normalized = "".join(ch for ch in normalized if not ch.isspace())
    normalized = normalized.strip()
    if not normalized:
        return None
    if not MOBILE_PATTERN.fullmatch(normalized):
        raise MobileValidationError("شمارهٔ موبایل نامعتبر است.")
    return normalized


__all__ = ["normalize_mobile", "MobileValidationError", "MOBILE_PATTERN"]

