# --- file: src/core/normalize.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Iterable, Literal, Sequence, cast, Final

from .enums import (
    GENDER_NORMALIZATION_MAP,
    REG_CENTER_NORMALIZATION_MAP,
    REG_STATUS_NORMALIZATION_MAP,
)
from .logging_utils import log_norm_error

SpecialSchoolsProvider = Callable[[int], Iterable[int]]

PERSIAN_TO_ASCII_DIGITS = str.maketrans(
    {
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
)
"""Translation table converting Persian and Arabic-Indic digits to ASCII."""

_HAKMAT_VARIANTS = {
    "hakmat",
    "hekmat",
    "حکمت",
    "حكمت",
    "حكـمت",
}

_ZERO_WIDTH_PATTERN = re.compile(r"[\u200c\u200d\u200e\u200f\u202a-\u202e]")

GENDER_ERROR: Final[str] = "جنسیت باید یکی از ۰ یا ۱ باشد."
REG_STATUS_ERROR: Final[str] = "وضعیت ثبت‌نام باید یکی از ۰/۱/۳ یا «حکمت» باشد."
REG_CENTER_ERROR: Final[str] = "کد مرکز باید یکی از ۰/۱/۲ باشد."
MOBILE_ERROR: Final[str] = "شمارهٔ همراه باید با ۰۹ شروع شود و دقیقاً ۱۱ رقم باشد."
NATIONAL_ID_ERROR: Final[str] = "کد ملی نامعتبر است (۱۰ رقم و چک‌سام)."
SCHOOL_CODE_ERROR: Final[str] = "کد مدرسه نامعتبر است."
NAME_ERROR: Final[str] = "نام نامعتبر است."


def normalize_digits(value: str) -> str:
    """Normalize a string by applying NFKC and converting digits to ASCII."""

    normalized = unicodedata.normalize("NFKC", value)
    return normalized.translate(PERSIAN_TO_ASCII_DIGITS)


def _prepare_key(value: object) -> str:
    """Canonicalize raw values for dictionary lookups."""

    text = normalize_digits(str(value))
    text = unicodedata.normalize("NFKC", text)
    text = " ".join(text.strip().lower().split())
    return text


def normalize_gender(value: object) -> Literal[0, 1]:
    """Normalize gender values to ``0`` (زن) or ``1`` (مرد)."""

    if value is None:
        log_norm_error("gender", value, "مقدار تهی", "gender.none")
        raise ValueError(GENDER_ERROR)
    if isinstance(value, bool):
        log_norm_error("gender", value, "مقدار بولی مجاز نیست", "gender.bool")
        raise ValueError(GENDER_ERROR)
    if isinstance(value, int):
        if value in (0, 1):
            return cast(Literal[0, 1], value)
        log_norm_error("gender", value, "خارج از دامنه", "gender.out_of_range")
        raise ValueError(GENDER_ERROR)

    key = _prepare_key(value)
    if key in GENDER_NORMALIZATION_MAP:
        return cast(Literal[0, 1], GENDER_NORMALIZATION_MAP[key])

    log_norm_error("gender", value, "شناسه نامعتبر", "gender.unknown")
    raise ValueError(GENDER_ERROR)


def normalize_reg_status(value: object) -> Literal[0, 1, 3]:
    """Normalize registration status into the strict domain ``{0, 1, 3}``."""

    if value is None:
        log_norm_error("reg_status", value, "مقدار تهی", "reg_status.none")
        raise ValueError(REG_STATUS_ERROR)
    if isinstance(value, bool):
        log_norm_error("reg_status", value, "مقدار بولی مجاز نیست", "reg_status.bool")
        raise ValueError(REG_STATUS_ERROR)
    if isinstance(value, int):
        if value in (0, 1, 3):
            return cast(Literal[0, 1, 3], value)
        log_norm_error("reg_status", value, "خارج از دامنه", "reg_status.out_of_range")
        raise ValueError(REG_STATUS_ERROR)

    key = _prepare_key(value)
    if key in REG_STATUS_NORMALIZATION_MAP:
        return cast(Literal[0, 1, 3], REG_STATUS_NORMALIZATION_MAP[key])
    if key in _HAKMAT_VARIANTS:
        return cast(Literal[0, 1, 3], 3)

    log_norm_error("reg_status", value, "شناسه نامعتبر", "reg_status.unknown")
    raise ValueError(REG_STATUS_ERROR)


def normalize_reg_center(value: object) -> Literal[0, 1, 2]:
    """Normalize registration center identifiers."""

    if value is None:
        log_norm_error("reg_center", value, "مقدار تهی", "reg_center.none")
        raise ValueError(REG_CENTER_ERROR)
    if isinstance(value, bool):
        log_norm_error("reg_center", value, "مقدار بولی مجاز نیست", "reg_center.bool")
        raise ValueError(REG_CENTER_ERROR)
    if isinstance(value, int):
        if value in (0, 1, 2):
            return cast(Literal[0, 1, 2], value)
        log_norm_error("reg_center", value, "خارج از دامنه", "reg_center.out_of_range")
        raise ValueError(REG_CENTER_ERROR)

    key = _prepare_key(value)
    if key in REG_CENTER_NORMALIZATION_MAP:
        return cast(Literal[0, 1, 2], REG_CENTER_NORMALIZATION_MAP[key])

    log_norm_error("reg_center", value, "شناسه نامعتبر", "reg_center.unknown")
    raise ValueError(REG_CENTER_ERROR)


_MOBILE_PATTERN = re.compile(r"^09\d{9}$")


def _normalize_mobile_prefix(digits: str) -> str:
    if digits.startswith("0098") and len(digits) > 4:
        return "0" + digits[4:]
    if digits.startswith("098") and len(digits) > 11:
        return "0" + digits[3:]
    if digits.startswith("98") and len(digits) > 10:
        return "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        return "0" + digits
    return digits


def normalize_mobile(value: object) -> str:
    """Canonicalize Iranian mobile numbers to the ``09XXXXXXXXX`` format."""

    if value is None:
        log_norm_error("mobile", value, "مقدار تهی", "mobile.none")
        raise ValueError(MOBILE_ERROR)
    if isinstance(value, bool):
        log_norm_error("mobile", value, "مقدار بولی مجاز نیست", "mobile.bool")
        raise ValueError(MOBILE_ERROR)

    text = normalize_digits(str(value))
    text = unicodedata.normalize("NFKC", text)
    digits = re.sub(r"\D", "", text)
    digits = _normalize_mobile_prefix(digits)

    if not _MOBILE_PATTERN.fullmatch(digits):
        log_norm_error("mobile", value, "الگوی نامعتبر", "mobile.invalid")
        raise ValueError(MOBILE_ERROR)
    return digits


def normalize_school_code(value: object | None) -> int | None:
    """Convert school code into an optional integer."""

    if value in (None, "", " ", "null", "None"):
        return None
    if isinstance(value, bool):
        log_norm_error("school_code", value, "مقدار بولی مجاز نیست", "school_code.bool")
        raise ValueError(SCHOOL_CODE_ERROR)

    text = _prepare_key(value)
    if not text or text == "null":
        return None
    if not re.fullmatch(r"-?\d+", text):
        log_norm_error("school_code", value, "شناسه نامعتبر", "school_code.unknown")
        raise ValueError(SCHOOL_CODE_ERROR)
    return int(text)


def normalize_int_sequence(values: object | None) -> list[int]:
    """Normalize sequences of integers from raw inputs."""

    if values is None:
        return []
    if isinstance(values, bool):
        log_norm_error(
            "mentor_special_schools",
            values,
            "مقدار بولی مجاز نیست",
            "mentor_special_schools.bool",
        )
        raise ValueError("فهرست مدارس ویژه نامعتبر است.")
    if isinstance(values, (str, bytes)):
        log_norm_error(
            "mentor_special_schools",
            values,
            "نوع ورودی اشتباه است",
            "mentor_special_schools.type",
        )
        raise ValueError("فهرست مدارس ویژه نامعتبر است.")
    if not isinstance(values, Iterable):
        log_norm_error(
            "mentor_special_schools",
            values,
            "قابل پیمایش نیست",
            "mentor_special_schools.iterable",
        )
        raise ValueError("فهرست مدارس ویژه نامعتبر است.")

    normalized: list[int] = []
    for item in values:  # type: ignore[assignment]
        if item in (None, "", " "):
            continue
        if isinstance(item, bool):
            log_norm_error(
                "mentor_special_schools",
                item,
                "مقدار بولی مجاز نیست",
                "mentor_special_schools.item_bool",
            )
            raise ValueError("فهرست مدارس ویژه نامعتبر است.")
        key = _prepare_key(item)
        if not re.fullmatch(r"-?\d+", key):
            log_norm_error(
                "mentor_special_schools",
                item,
                "شناسه نامعتبر",
                "mentor_special_schools.item_invalid",
            )
            raise ValueError("فهرست مدارس ویژه نامعتبر است.")
        normalized.append(int(key))
    return normalized


def normalize_name(value: object | None) -> str | None:
    """Normalize textual names with RTL-specific rules."""

    if value in (None, "", " "):
        return None
    if isinstance(value, bool):
        log_norm_error("name", value, "مقدار بولی مجاز نیست", "name.bool")
        raise ValueError(NAME_ERROR)

    text = normalize_digits(str(value))
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ك", "ک").replace("ي", "ی")
    text = _ZERO_WIDTH_PATTERN.sub("", text)
    stripped = text.strip()
    collapsed = " ".join(stripped.split())
    if not collapsed:
        log_norm_error("name", value, "نام پس از پاکسازی تهی شد", "name.empty_after_clean")
        return None
    if collapsed != stripped:
        log_norm_error("name", value, "نام پاکسازی شد", "name.cleaned")
    return collapsed


def derive_student_type(
    school_code: object | None,
    mentor_special_schools: Sequence[int] | None,
    *,
    roster_year: int | None = None,
    provider: SpecialSchoolsProvider | None = None,
) -> Literal[0, 1]:
    """Derive the student type flag based on school membership."""

    normalized_school_code = normalize_school_code(school_code)
    if normalized_school_code is None:
        return cast(Literal[0, 1], 0)

    roster: set[int] = set()
    if provider is not None and roster_year is not None:
        try:
            raw_roster = provider(roster_year)
        except Exception as exc:  # pragma: no cover - defensive logging path
            log_norm_error(
                "student_type",
                roster_year,
                f"خطای دریافت داده: {exc}",
                "student_type.provider_error",
            )
            raw_roster = []
        for item in raw_roster:
            try:
                normalized_item = normalize_school_code(item)
            except ValueError:
                log_norm_error(
                    "student_type",
                    item,
                    "کد مدرسه ویژه نامعتبر",
                    "student_type.provider_invalid",
                )
                continue
            if normalized_item is not None:
                roster.add(normalized_item)
    elif mentor_special_schools is not None:
        roster.update(normalize_int_sequence(list(mentor_special_schools)))

    if normalized_school_code in roster:
        return cast(Literal[0, 1], 1)
    return cast(Literal[0, 1], 0)


def normalize_national_id(value: object) -> str:
    """Normalize national ID ensuring an exact 10-digit ASCII string."""

    if value is None:
        log_norm_error("national_id", value, "مقدار تهی", "national_id.none")
        raise ValueError(NATIONAL_ID_ERROR)
    if isinstance(value, bool):
        log_norm_error("national_id", value, "مقدار بولی مجاز نیست", "national_id.bool")
        raise ValueError(NATIONAL_ID_ERROR)

    text = normalize_digits(str(value))
    text = unicodedata.normalize("NFKC", text).strip()
    digits = re.sub(r"\D", "", text)
    if not re.fullmatch(r"\d{10}", digits):
        log_norm_error("national_id", value, "الگوی نامعتبر", "national_id.invalid")
        raise ValueError(NATIONAL_ID_ERROR)

    numbers = [int(ch) for ch in digits]
    checksum = numbers[-1]
    weighted_sum = sum(numbers[i] * (10 - i) for i in range(9))
    remainder = weighted_sum % 11
    expected = remainder if remainder < 2 else 11 - remainder

    if expected != checksum:
        log_norm_error("national_id", value, "چک‌سام نامعتبر", "national_id.checksum")
        raise ValueError(NATIONAL_ID_ERROR)

    return digits


__all__ = [
    "GENDER_ERROR",
    "REG_STATUS_ERROR",
    "REG_CENTER_ERROR",
    "MOBILE_ERROR",
    "NATIONAL_ID_ERROR",
    "SCHOOL_CODE_ERROR",
    "NAME_ERROR",
    "SpecialSchoolsProvider",
    "derive_student_type",
    "normalize_digits",
    "normalize_gender",
    "normalize_int_sequence",
    "normalize_mobile",
    "normalize_name",
    "normalize_national_id",
    "normalize_reg_center",
    "normalize_reg_status",
    "normalize_school_code",
]
