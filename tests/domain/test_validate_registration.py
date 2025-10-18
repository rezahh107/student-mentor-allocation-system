from __future__ import annotations

import re

import pytest

from tooling.domain import (
    AcademicYearProvider,
    ValidationError,
    validate_registration,
)


@pytest.fixture()
def year_provider() -> AcademicYearProvider:
    return AcademicYearProvider({2024: "24", 2025: "25"})


def test_phase1_normalization_edges(year_provider: AcademicYearProvider) -> None:
    payload = {
        "reg_center": "0",
        "reg_status": "0",
        "gender": 1,
        "mobile": "٠٩١٢٣٤٥٦٧٨٩",
        "text_fields_desc": "\u200cنمونه\u200f",
        "national_id": "٠٠٦۱۲۳۴۵۶۷\u200c",
        "year": "2024",
        "counter": "٠١٣٥٧٣٦٧٨",
    }
    result = validate_registration(payload, year_provider)
    assert result["mobile"] == "09123456789"
    assert result["national_id"] == "0061234567"
    assert result["counter"] == "013573678"
    assert result["text_fields"]["text_fields_desc"] == "نمونه"


def test_validation_rules_raise(year_provider: AcademicYearProvider) -> None:
    payload = {"reg_center": 5, "reg_status": 1, "gender": 0, "year": 2024}
    with pytest.raises(ValidationError) as exc:
        validate_registration(payload, year_provider)
    assert "خارج از دامنه" in str(exc.value)

    bad_counter = {
        "reg_center": 1,
        "reg_status": 0,
        "gender": 0,
        "year": 2024,
        "counter": "abc",
    }
    with pytest.raises(ValidationError) as counter_exc:
        validate_registration(bad_counter, year_provider)
    assert "شناسه دانش آموز نامعتبر است" in str(counter_exc.value)


def test_counter_derivations_and_regex(year_provider: AcademicYearProvider) -> None:
    payload = {
        "reg_center": "1",
        "reg_status": "3",
        "gender": 1,
        "mobile": "09123456789",
        "national_id": "0061234567",
        "year": "2025",
        "counter": "٠٢٣٥٧٣٦٧٨",
    }
    result = validate_registration(payload, year_provider)
    assert result["gender_prefix"] == "357"
    assert re.fullmatch(r"^\d{2}(357|373)\d{4}$", result["counter"])
    assert result["counter"][2:5] == result["gender_prefix"]
    assert result["year_code"] == "25"


def test_derived_fields(year_provider: AcademicYearProvider) -> None:
    payload = {
        "reg_center": 2,
        "reg_status": 3,
        "gender": 0,
        "mobile": "09123456789",
        "national_id": "0061234567",
        "year": 2024,
        "counter": "123735678",
    }
    result = validate_registration(payload, year_provider)
    assert result["gender_prefix"] == "373"
    assert result["student_type"] == "special-2024"
    assert result["year_code"] == "24"
