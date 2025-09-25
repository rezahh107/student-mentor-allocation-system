"""پوشش تست ماژول legacy مربوط به API."""
from __future__ import annotations

from datetime import date, datetime
from importlib import util
import sys
from pathlib import Path
from typing import Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC = util.spec_from_file_location("legacy_api_models", PROJECT_ROOT / "src" / "api" / "models.py")
assert _SPEC and _SPEC.loader
_API_MODELS = util.module_from_spec(_SPEC)
sys.modules.setdefault("legacy_api_models", _API_MODELS)
_SPEC.loader.exec_module(_API_MODELS)  # type: ignore[arg-type]

StudentDTO = _API_MODELS.StudentDTO
validate_iranian_phone = _API_MODELS.validate_iranian_phone
validate_national_code = _API_MODELS.validate_national_code
migrate_student_dto = _API_MODELS.migrate_student_dto


def _valid_national_code(seed: str = "002233445") -> str:
    digits = seed.strip()
    assert digits.isdigit() and len(digits) == 9
    for check_digit in range(10):
        candidate = f"{digits}{check_digit}"
        checksum = sum(int(candidate[i]) * (10 - i) for i in range(9))
        remainder = checksum % 11
        expected = remainder if remainder < 2 else 11 - remainder
        if expected == check_digit:
            return candidate
    raise AssertionError("failed to construct national code")


def test_validate_national_code_variants() -> None:
    """اعتبارسنجی کدملی باید حالات مرزی را پوشش دهد."""

    good_code = _valid_national_code()
    assert validate_national_code(good_code)
    assert not validate_national_code("1111111111")
    assert not validate_national_code("123456789")
    assert not validate_national_code("abcdefghij")


def test_validate_iranian_phone_formats() -> None:
    """شماره‌های موبایل و تلفن ثابت باید شناسایی شوند."""

    assert validate_iranian_phone("09121234567")
    assert validate_iranian_phone("+989121234567")
    assert validate_iranian_phone("021-88990000")
    assert not validate_iranian_phone("12345")


def test_student_dto_alias_properties() -> None:
    """خواص legacy مانند level/id باید کار کنند."""

    now = datetime(2024, 1, 1)
    dto = StudentDTO(
        student_id=5,
        counter="2400010001",
        first_name="رضا",
        last_name="کاظمی",
        national_code=_valid_national_code("123123123"),
        phone="09120000000",
        birth_date=date(2004, 5, 12),
        gender=1,
        education_status=1,
        registration_status=2,
        center=3,
        grade_level="konkoori",
        school_type="normal",
        school_code=None,
        created_at=now,
        updated_at=now,
    )

    assert dto.id == 5
    assert dto.level == "konkoori"
    dto.level = "tajrobi"
    assert dto.grade_level == "tajrobi"


def test_migrate_student_dto_random_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """مهاجرت باید فیلدهای legacy را نگاشت و مقادیر تصادفی را پایدار کند."""

    sequence: Iterator[int] = iter((
        1234567890,  # national_code
        765432109,   # phone
        321,         # counter serial
    ))

    def fake_randint(low: int, high: int) -> int:
        try:
            return next(sequence)
        except StopIteration as exc:  # pragma: no cover - محافظتی
            raise AssertionError("randint called too often") from exc

    monkeypatch.setattr(_API_MODELS.random, "randint", fake_randint)

    legacy = {
        "id": 77,
        "name": "علی احمدی",
        "registration_type": 1,
        "center": 2,
        "level": "motavassete2",
        "school_type": 1,
        "created_at": datetime(2023, 6, 1, 12, 0, 0),
        "gender": 1,
        "education_status": 1,
        "school_code": "SCH-99",
    }

    dto = migrate_student_dto(legacy)

    assert dto.student_id == 77
    assert dto.registration_status == 1
    assert dto.grade_level == "motavassete2"
    assert dto.school_type == "school"
    assert dto.national_code == "1234567890"
    assert dto.phone == "09765432109"
    assert dto.counter.endswith("0321")
    assert dto.updated_at >= dto.created_at
