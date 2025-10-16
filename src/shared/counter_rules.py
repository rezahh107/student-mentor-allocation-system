# -*- coding: utf-8 -*-
from __future__ import annotations

"""Single source of truth for counter generation rules."""

from hashlib import blake2b
from typing import Final, Mapping, Pattern
import re

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

COUNTER_PREFIX_MAP: Final[Mapping[int, str]] = {0: "373", 1: "357"}
"""Normalized mapping gender→prefix.

The canonical mapping ensures female (0) counters start with ``373`` and male
ones (1) with ``357``. The values are four characters wide strings as expected
by downstream Excel exports and validation layers.
"""

COUNTER_REGEX: Final[Pattern[str]] = re.compile(r"^\d{2}(357|373)\d{4}$")
"""Validates counters of the form ``YY + (357|373) + ####``."""


def gender_prefix(gender_code: int) -> str:
    """Return the canonical counter prefix for a normalized gender code."""

    try:
        return COUNTER_PREFIX_MAP[int(gender_code)]
    except (KeyError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError("کد جنسیت برای شمارنده معتبر نیست") from exc


def stable_counter_hash(seed: str) -> int:
    """Deterministic hash helper for fairness jitter and sequencing."""

    digest = blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def validate_counter(value: str) -> str:
    """Normalize and validate counters against the canonical regex."""

    normalized = (value or "").translate(_DIGIT_MAP)
    normalized = normalized.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    normalized = re.sub(r"\s+", "", normalized)
    if not COUNTER_REGEX.fullmatch(normalized):
        raise ValueError("فرمت شمارنده معتبر نیست.")
    return normalized


__all__ = [
    "COUNTER_PREFIX_MAP",
    "COUNTER_REGEX",
    "gender_prefix",
    "stable_counter_hash",
    "validate_counter",
]
