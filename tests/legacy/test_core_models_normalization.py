"""تست‌های legacy برای مدل‌ها و نرمال‌سازی هسته."""
from __future__ import annotations

import os
from typing import Iterable

import pytest

from sma.core.models import (
    Mentor,
    StudentNormalized,
    _normalize_special_schools,
    _normalize_student_type_value,
    to_student_normalized,
)


def _build_valid_national_id(seed: str = "001234567") -> str:
    """ساخت کدملی معتبر با الگوریتم mod-11."""

    digits = seed.strip().replace(" ", "")
    assert digits.isdigit() and len(digits) == 9, "seed must provide 9 digits"
    for check_digit in range(10):
        candidate = f"{digits}{check_digit}"
        checksum = sum(int(candidate[i]) * (10 - i) for i in range(9))
        remainder = checksum % 11
        expected = remainder if remainder < 2 else 11 - remainder
        if expected == check_digit:
            return candidate
    raise AssertionError("unable to construct valid national id")


def _dummy_provider(_: int) -> Iterable[object]:
    """ارائه‌دهندهٔ مدارس ویژه با دادهٔ مخدوش."""

    return ["کدنامعتبر", "۱۲۳۴۵۶۷"]


def test_to_student_normalized_aliases_and_provider_override() -> None:
    """آزمون پذیرش ورودی legacy و مشتق‌شدن student_type از provider."""

    national_id = _build_valid_national_id()
    raw_payload = {
        "sex": "دختر",
        "status": "حکمت",
        "centre": "2",
        "cellphone": "۰۹۱۲۳۴۵۶۷۸۹",
        "nid": national_id,
        "mentorSpecialSchools": ["۱۲۳۴۵", "۰۰۱۰۰"],
        "studentType": "0",
        "name": " زهرا‌نوری ",
        "school_code": "۱۲۳۴۵",
    }

    model = to_student_normalized(
        raw_payload,
        roster_year=1402,
        special_school_provider=lambda year: ("۰۰۱۰۰", "۱۲۳۴۵") if year == 1402 else (),
    )

    assert isinstance(model, StudentNormalized)
    assert model.gender == 0
    assert model.reg_status == 3
    assert model.reg_center == 2
    assert model.mobile == "09123456789"
    assert model.national_id == national_id
    assert model.student_type == 1, "student_type must be derived from provider roster"


def test_to_student_normalized_handles_invalid_provider_items() -> None:
    """تضمین می‌کند مقادیر مخدوش provider باعث سقوط نمی‌شود."""

    national_id = _build_valid_national_id("111222333")
    raw_payload = {
        "gender": 1,
        "reg_status": "0",
        "reg_center": "1",
        "mobile": "09120000000",
        "national_id": national_id,
        "school_code": "54321",
    }

    model = to_student_normalized(
        raw_payload,
        roster_year=1401,
        special_school_provider=_dummy_provider,
    )

    assert model.student_type == 0


def test_to_student_normalized_logs_invalid_name(caplog: pytest.LogCaptureFixture) -> None:
    """نام بولی باید ثبت خطا شده و مدل معتبر بازگرداند."""

    national_id = _build_valid_national_id("210210210")
    raw_payload = {
        "gender": 0,
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09125551234",
        "national_id": national_id,
        "school_code": "1000",
        "name": True,
    }

    with caplog.at_level("INFO"):
        model = to_student_normalized(raw_payload)

    assert model.student_type == 0
    assert any("name.invalid" in message for message in caplog.text.splitlines())


def test_normalize_student_type_value_validation() -> None:
    """ارزش‌های غیرمجاز باید خطای فارسی ایجاد کنند."""

    assert _normalize_student_type_value(1) == 1
    assert _normalize_student_type_value("۰") == 0
    with pytest.raises(ValueError, match="نوع دانش‌آموز نامعتبر است."):
        _normalize_student_type_value(None)
    with pytest.raises(ValueError, match="نوع دانش‌آموز نامعتبر است."):
        _normalize_student_type_value(True)
    with pytest.raises(ValueError, match="نوع دانش‌آموز نامعتبر است."):
        _normalize_student_type_value(7)
    with pytest.raises(ValueError, match="نوع دانش‌آموز نامعتبر است."):
        _normalize_student_type_value("الف")


def test_to_student_normalized_rejects_non_mapping() -> None:
    """ورودی تهی یا نامعتبر باید خطا ایجاد کند."""

    with pytest.raises(ValueError, match="داده ورودی نامعتبر است."):
        to_student_normalized(None)


def test_normalize_special_schools_accepts_persian_digits() -> None:
    """رشته‌های ارقام فارسی باید به تاپل اعداد تبدیل شوند."""

    result = _normalize_special_schools(["۱۲۳", "004", " ۵ "])
    assert result == (123, 4, 5)


def test_mentor_remaining_capacity() -> None:
    """ظرفیت باقیمانده منتور باید صحیح محاسبه شود."""

    mentor = Mentor(id=1, gender=1, supported_grades=(1,), max_capacity=12, current_students=7, center_id=2)
    assert mentor.remaining_capacity() == 5


@pytest.mark.skipif(
    not os.environ.get("DISPLAY"),
    reason="GUI_HEADLESS_SKIPPED: محیط فاقد نمایشگر است.",
)
def test_headless_environment_marker() -> None:
    """تست اطمینان از فعال بودن نمایشگر در محیط‌های GUI."""

    assert os.environ.get("DISPLAY")
