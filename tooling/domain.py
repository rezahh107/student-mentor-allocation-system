from __future__ import annotations

"""Domain helpers for registration validation and derived fields."""

from dataclasses import dataclass
from typing import Mapping
import re
import unicodedata

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u200f\ufeff]")
_ARABIC_YEH = "ي"
_ARABIC_KEHEH = "ك"
_PERSIAN_YEH = "ی"
_PERSIAN_KEHEH = "ک"
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_REG_CENTER = {0, 1, 2}
_REG_STATUS = {0, 1, 3}
_GENDER_PREFIX = {0: "373", 1: "357"}
_PHONE_PATTERN = re.compile(r"^09\d{9}$")
_COUNTER_PATTERN = re.compile(r"^\d{2}(357|373)\d{4}$")


class ValidationError(ValueError):
    """Raised when domain validation fails with a deterministic Persian message."""


@dataclass
class AcademicYearProvider:
    """Minimal provider for deriving academic year codes without wall clock."""

    year_codes: dict[int, str]

    def code(self, year: int) -> str:
        try:
            return self.year_codes[year]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValidationError("کد سال تحصیلی نامعتبر است.") from exc


@dataclass
class SpecialSchoolsRoster:
    """Derive the student type from the configured roster."""

    year: int

    def resolve(self) -> str:
        return f"special-{self.year}"


def normalize_text(value: str) -> str:
    """Fold digits, normalise Unicode, and strip zero-width/control characters."""

    folded = value.translate(_ARABIC_DIGITS).translate(_PERSIAN_DIGITS)
    folded = folded.replace(_ARABIC_YEH, _PERSIAN_YEH).replace(_ARABIC_KEHEH, _PERSIAN_KEHEH)
    folded = unicodedata.normalize("NFKC", folded)
    folded = _ZERO_WIDTH.sub("", folded)
    return folded.strip()


def _require_int(value: object, message: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise ValidationError(message)


def validate_registration(
    payload: Mapping[str, object],
    year_provider: AcademicYearProvider,
) -> dict[str, object]:
    """Normalise and validate a registration payload."""

    reg_center = _require_int(
        payload.get("reg_center"),
        "درخواست نامعتبر است؛ مقادیر reg_center یا reg_status خارج از دامنه است.",
    )
    reg_status = _require_int(
        payload.get("reg_status"),
        "درخواست نامعتبر است؛ مقادیر reg_center یا reg_status خارج از دامنه است.",
    )
    if reg_center not in _REG_CENTER or reg_status not in _REG_STATUS:
        raise ValidationError("درخواست نامعتبر است؛ مقادیر reg_center یا reg_status خارج از دامنه است.")

    gender = _require_int(payload.get("gender", 0), "جنسیت نامعتبر است.")
    if gender not in _GENDER_PREFIX:
        raise ValidationError("جنسیت نامعتبر است.")

    year = _require_int(payload.get("year", 0), "کد سال تحصیلی نامشخص است.")
    year_code = year_provider.code(year)

    mobile = normalize_text(str(payload.get("mobile") or ""))
    if mobile and not _PHONE_PATTERN.fullmatch(mobile):
        raise ValidationError("شماره همراه نامعتبر است.")

    counter_raw = normalize_text(str(payload.get("counter") or ""))
    if counter_raw and not _COUNTER_PATTERN.fullmatch(counter_raw):
        raise ValidationError("شناسه دانش آموز نامعتبر است.")

    national_id = normalize_text(str(payload.get("national_id") or ""))

    text_fields = {
        key: normalize_text(str(value or ""))
        for key, value in payload.items()
        if key.startswith("text_")
    }

    result = dict(payload)
    result.update(
        {
            "reg_center": reg_center,
            "reg_status": reg_status,
            "gender": gender,
            "year": year,
            "year_code": year_code,
            "mobile": mobile,
            "counter": counter_raw,
            "national_id": national_id,
            "text_fields": text_fields,
            "gender_prefix": _GENDER_PREFIX[gender],
            "student_type": SpecialSchoolsRoster(year).resolve(),
        }
    )
    return result
