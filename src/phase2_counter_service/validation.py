# -*- coding: utf-8 -*-
"""Input validation routines for the counter service."""
from __future__ import annotations

import re
import unicodedata
from typing import Tuple

from .errors import counter_exhausted, invalid_gender, invalid_national_id, invalid_year_code
from .types import GenderLiteral
from src.shared.counter_rules import COUNTER_PREFIX_MAP, COUNTER_REGEX, gender_prefix

NATIONAL_ID_PATTERN = re.compile(r"^\d{10}$")
YEAR_CODE_PATTERN = re.compile(r"^\d{2}$")
COUNTER_PATTERN = COUNTER_REGEX
COUNTER_PREFIX = dict(COUNTER_PREFIX_MAP)
COUNTER_MAX_SEQ = 9999
PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
ZERO_WIDTH_TABLE = str.maketrans('', '', '\u200b\ufeff')


def normalize(text: str) -> str:
    normalized = unicodedata.normalize('NFKC', text or '').translate(PERSIAN_DIGITS)
    normalized = normalized.translate(ZERO_WIDTH_TABLE)
    return normalized.strip()


def ensure_valid_inputs(national_id: str, gender: GenderLiteral, year_code: str) -> Tuple[str, str]:
    normalized_nid = normalize(national_id)
    normalized_year = normalize(year_code)

    if not normalized_nid or not NATIONAL_ID_PATTERN.fullmatch(normalized_nid):
        raise invalid_national_id("کد ملی باید دقیقا ۱۰ رقم باشد.")

    try:
        gender_prefix(gender)
    except ValueError:
        raise invalid_gender("جنسیت باید ۰ (زن) یا ۱ (مرد) باشد.")

    if not normalized_year or not YEAR_CODE_PATTERN.fullmatch(normalized_year):
        raise invalid_year_code("کد سال باید دقیقا دو رقم باشد.")

    return normalized_nid, normalized_year


def ensure_counter_format(counter: str) -> str:
    value = normalize(counter)
    if not COUNTER_PATTERN.fullmatch(value):
        raise counter_exhausted("فرمت شمارنده معتبر نیست یا ظرفیت پایان یافته است.")
    return value


def ensure_sequence_bounds(seq: int) -> int:
    if not (1 <= seq <= COUNTER_MAX_SEQ):
        raise counter_exhausted("محدوده شماره شمارنده به پایان رسیده است.")
    return seq
