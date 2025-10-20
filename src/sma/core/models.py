# --- file: src/core/models.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}
# Backward compatibility aliases are documented next to extraction helpers.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping, Sequence, cast

from pydantic import BaseModel, ConfigDict, field_validator

from .logging_utils import log_norm_error
from .normalize import (
    NAME_ERROR,
    SpecialSchoolsProvider,
    derive_student_type,
    normalize_digits,
    normalize_gender,
    normalize_int_sequence,
    normalize_mobile,
    normalize_name,
    normalize_national_id,
    normalize_reg_center,
    normalize_reg_status,
    normalize_school_code,
)


@dataclass(slots=True)
class Student:
    """Represents a student waiting for mentor assignment."""

    id: int
    gender: int
    grade_level: int
    center_id: int
    name: str | None = None
    registration_status: int | None = None
    academic_status: int | None = None
    is_school_student: bool | None = None


@dataclass(slots=True)
class Mentor:
    """Represents a mentor capable of supporting students."""

    id: int
    gender: int
    supported_grades: Sequence[int]
    max_capacity: int
    current_students: int
    center_id: int
    primary_grade: int | None = None
    name: str | None = None
    speciality_tags: Sequence[str] | None = None

    def remaining_capacity(self) -> int:
        """Number of seats still available for this mentor."""

        return self.max_capacity - self.current_students


def _normalize_student_type_value(value: object) -> Literal[0, 1]:
    """Normalize raw ``student_type`` payloads for comparison and validation."""

    if value is None:
        raise ValueError("نوع دانش‌آموز نامعتبر است.")
    if isinstance(value, bool):
        log_norm_error("student_type", value, "مقدار بولی مجاز نیست", "student_type.bool")
        raise ValueError("نوع دانش‌آموز نامعتبر است.")
    if isinstance(value, int):
        if value in (0, 1):
            return cast(Literal[0, 1], value)
        log_norm_error("student_type", value, "خارج از دامنه", "student_type.out_of_range")
        raise ValueError("نوع دانش‌آموز نامعتبر است.")
    text = normalize_digits(str(value)).strip()
    if text in {"0", "1"}:
        return cast(Literal[0, 1], int(text))
    log_norm_error("student_type", value, "شناسه نامعتبر", "student_type.unknown")
    raise ValueError("نوع دانش‌آموز نامعتبر است.")


class StudentNormalized(BaseModel):
    """Normalized data transfer object for student registration records."""

    gender: Literal[0, 1]
    reg_status: Literal[0, 1, 3]
    reg_center: Literal[0, 1, 2]
    mobile: str
    national_id: str
    school_code: int | None = None
    student_type: Literal[0, 1]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("gender", mode="before")
    @classmethod
    def _validate_gender(cls, value: object) -> Literal[0, 1]:
        return normalize_gender(value)

    @field_validator("reg_status", mode="before")
    @classmethod
    def _validate_reg_status(cls, value: object) -> Literal[0, 1, 3]:
        return normalize_reg_status(value)

    @field_validator("reg_center", mode="before")
    @classmethod
    def _validate_reg_center(cls, value: object) -> Literal[0, 1, 2]:
        return normalize_reg_center(value)

    @field_validator("mobile", mode="before")
    @classmethod
    def _validate_mobile(cls, value: object) -> str:
        return normalize_mobile(value)

    @field_validator("national_id", mode="before")
    @classmethod
    def _validate_national_id(cls, value: object) -> str:
        return normalize_national_id(value)

    @field_validator("school_code", mode="before")
    @classmethod
    def _validate_school_code(cls, value: object | None) -> int | None:
        return normalize_school_code(value)

    @field_validator("student_type", mode="before")
    @classmethod
    def _validate_student_type(cls, value: object) -> Literal[0, 1]:
        return _normalize_student_type_value(value)


_GENDER_ALIASES = ("gender", "sex", "Gender")
_REG_STATUS_ALIASES = (
    "reg_status",
    "status",
    "registration_status",
    "status_reg",
    "regStatus",
)
_REG_CENTER_ALIASES = (
    "reg_center",
    "center",
    "centre",
    "regCentre",
    "center_id",
    "reg_center_id",
    "registration_center",
)
_MOBILE_ALIASES = ("mobile", "cell", "cellphone")
_NATIONAL_ID_ALIASES = ("national_id", "nid", "meli_code")
_STUDENT_TYPE_ALIASES = ("student_type", "studentType", "type")
_NAME_ALIASES = ("name", "full_name", "fullName")
_SPECIAL_SCHOOLS_ALIASES = (
    "mentor_special_schools",
    "special_schools",
    "schools_special",
    "mentorSpecialSchools",
)
# Backward compatibility aliases: legacy payloads used British spelling and snake/camel cases.


def _extract_alias(data: Mapping[str, Any], *keys: str) -> Any:
    """Extract the first matching key from aliases."""

    for key in keys:
        if key in data:
            return data[key]
    return None


def _normalize_special_schools(values: Any) -> tuple[int, ...]:
    """Normalize mentor special school identifiers to a sequence of integers."""

    normalized = normalize_int_sequence(values)
    return tuple(normalized)


def to_student_normalized(
    raw: Mapping[str, Any],
    *,
    roster_year: int | None = None,
    special_school_provider: SpecialSchoolsProvider | None = None,
) -> StudentNormalized:
    """Create a :class:`StudentNormalized` model from raw input data."""

    if raw is None or not isinstance(raw, Mapping):
        raise ValueError("داده ورودی نامعتبر است.")

    gender_raw = _extract_alias(raw, *_GENDER_ALIASES)
    status_raw = _extract_alias(raw, *_REG_STATUS_ALIASES)
    center_raw = _extract_alias(raw, *_REG_CENTER_ALIASES)
    mobile_raw = _extract_alias(raw, *_MOBILE_ALIASES)
    national_id_raw = _extract_alias(raw, *_NATIONAL_ID_ALIASES)
    incoming_student_type = _extract_alias(raw, *_STUDENT_TYPE_ALIASES)
    name_raw = _extract_alias(raw, *_NAME_ALIASES)

    special_raw = _extract_alias(raw, *_SPECIAL_SCHOOLS_ALIASES)
    mentor_special_schools = _normalize_special_schools(special_raw)

    school_code = normalize_school_code(raw.get("school_code"))
    derived_student_type = derive_student_type(
        school_code,
        mentor_special_schools,
        roster_year=roster_year,
        provider=special_school_provider,
    )

    if incoming_student_type is not None:
        log_norm_error(
            "student_type",
            incoming_student_type,
            "مقدار ورودی نادیده گرفته شد",
            "student_type.ignored_input",
        )

    payload: Dict[str, Any] = {
        "gender": gender_raw,
        "reg_status": status_raw,
        "reg_center": center_raw,
        "mobile": mobile_raw,
        "national_id": national_id_raw,
        "school_code": school_code,
        "student_type": derived_student_type,
    }

    model = StudentNormalized.model_validate(payload)

    if name_raw is not None:
        try:
            normalize_name(name_raw)
        except ValueError:
            log_norm_error("name", name_raw, NAME_ERROR, "name.invalid")
    return model


__all__ = [
    "Mentor",
    "Student",
    "StudentNormalized",
    "to_student_normalized",
]
