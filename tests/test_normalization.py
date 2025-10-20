# --- file: tests/test_normalization.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}
from __future__ import annotations

import pytest

pytest.importorskip(
    "hypothesis",
    reason="DEPENDENCY_MISSING: کتابخانه Hypothesis برای این محیط نصب نشده است.",
)
from hypothesis import given, strategies as st
from pydantic import ValidationError

from sma.core.models import StudentNormalized, to_student_normalized
from sma.core.normalize import (
    GENDER_ERROR,
    MOBILE_ERROR,
    NATIONAL_ID_ERROR,
    REG_CENTER_ERROR,
    REG_STATUS_ERROR,
    SCHOOL_CODE_ERROR,
    derive_student_type,
    normalize_digits,
    normalize_gender,
    normalize_int_sequence,
    normalize_mobile,
    normalize_national_id,
    normalize_reg_center,
    normalize_reg_status,
    normalize_school_code,
)


def test_normalize_gender_variants() -> None:
    """Ensure gender normalization accepts multilingual aliases."""

    assert normalize_gender("زن") == 0
    assert normalize_gender(" female ") == 0
    assert normalize_gender("1") == 1
    assert normalize_gender("پسر") == 1


def test_normalize_gender_invalid() -> None:
    """Invalid gender inputs must raise ``ValueError`` with Persian message."""

    with pytest.raises(ValueError) as exc:
        normalize_gender("unknown")
    assert str(exc.value) == GENDER_ERROR


def test_normalize_gender_numeric_paths() -> None:
    """Ensure numeric gender inputs pass through strict normalization."""

    assert normalize_gender(0) == 0
    with pytest.raises(ValueError) as exc:
        normalize_gender(5)
    assert str(exc.value) == GENDER_ERROR


def test_reg_status_hakmat() -> None:
    """The free-form "Hakmat" must map to code 3."""

    assert normalize_reg_status("Hakmat") == 3
    assert normalize_reg_status("حکمت") == 3


def test_normalize_reg_status_numeric_paths() -> None:
    """Numeric status codes should validate domain membership."""

    assert normalize_reg_status(3) == 3
    with pytest.raises(ValueError) as exc:
        normalize_reg_status(7)
    assert str(exc.value) == REG_STATUS_ERROR


def test_normalize_reg_center_invalid() -> None:
    """Reject invalid registration centers."""

    with pytest.raises(ValueError) as exc:
        normalize_reg_center(5)
    assert str(exc.value) == REG_CENTER_ERROR


def test_normalize_reg_center_numeric_paths() -> None:
    """Registration centers accept only the whitelisted numeric values."""

    assert normalize_reg_center(2) == 2
    with pytest.raises(ValueError) as exc:
        normalize_reg_center(3)
    assert str(exc.value) == REG_CENTER_ERROR


def test_normalize_mobile_variants() -> None:
    """Normalize various Iranian mobile number formats."""

    assert normalize_mobile("+98 912 123 4567") == "09121234567"
    assert normalize_mobile("00989121234567") == "09121234567"
    assert normalize_mobile("۰۹۱۲۳۴۵۶۷۸۹") == "09123456789"


def test_normalize_mobile_strips_short_national_prefix() -> None:
    """Numbers missing the leading zero gain it during normalization."""

    assert normalize_mobile("9123456789") == "09123456789"


def test_normalize_mobile_invalid() -> None:
    """Ensure invalid numbers fail normalization."""

    with pytest.raises(ValueError) as exc:
        normalize_mobile("123")
    assert str(exc.value) == MOBILE_ERROR


def test_normalize_national_id() -> None:
    """Normalize national identifier digits with unicode input."""

    assert normalize_national_id("۰۰۶۰۳۰۸۶۴۸") == "0060308648"


def test_normalize_national_id_invalid() -> None:
    """Invalid national identifiers raise a Persian ``ValueError``."""

    with pytest.raises(ValueError) as exc:
        normalize_national_id("1234")
    assert str(exc.value) == NATIONAL_ID_ERROR


def test_derive_student_type_membership() -> None:
    """Student type equals 1 if the school code exists in the mentor list."""

    assert derive_student_type("101", [101, 202]) == 1
    assert derive_student_type("101", []) == 0
    assert derive_student_type(None, [101]) == 0


def test_normalize_school_code_paths() -> None:
    """School code normalization handles null-like values and errors."""

    assert normalize_school_code(" null ") is None
    assert normalize_school_code("۰۱") == 1
    assert normalize_school_code("۱۰۱") == 101
    with pytest.raises(ValueError) as exc:
        normalize_school_code("ABC")
    assert str(exc.value) == SCHOOL_CODE_ERROR


def test_normalize_int_sequence_behaviour() -> None:
    """Special school lists normalize digits and reject invalid values."""

    assert normalize_int_sequence(["۱۰۱", 202]) == [101, 202]
    assert normalize_int_sequence(None) == []
    with pytest.raises(ValueError, match="فهرست مدارس ویژه نامعتبر است"):
        normalize_int_sequence("101")
    with pytest.raises(ValueError, match="فهرست مدارس ویژه نامعتبر است"):
        normalize_int_sequence(["bad"])


def test_to_student_normalized_aliases() -> None:
    """Backward compatible aliases should be respected."""

    raw = {
        "sex": "male",
        "status": "1",
        "center": "2",
        "mobile": "00989123456789",
        "national_id": "1332073689",
        "school_code": None,
        "mentor_special_schools": [],
    }
    normalized = to_student_normalized(raw)
    assert normalized.gender == 1
    assert normalized.reg_status == 1
    assert normalized.reg_center == 2
    assert normalized.student_type == 0


def test_to_student_normalized_happy_path() -> None:
    """End-to-end normalization using the provided example."""

    raw = {
        "gender": "زن",
        "mobile": "+98 912 123 4567",
        "reg_status": "Hakmat",
        "reg_center": "1",
        "national_id": "۱۳۳۲۰۷۳۶۸۹",
        "school_code": "101",
        "mentor_special_schools": [101],
    }
    normalized = to_student_normalized(raw)
    assert normalized.gender == 0
    assert normalized.mobile == "09121234567"
    assert normalized.reg_status == 3
    assert normalized.reg_center == 1
    assert normalized.student_type == 1


def test_to_student_normalized_invalid_mobile() -> None:
    """Invalid mobile numbers bubble up as Persian ``ValidationError`` messages."""

    raw = {
        "gender": "زن",
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09123",
        "national_id": "1332073689",
        "school_code": None,
        "mentor_special_schools": [],
    }
    with pytest.raises(ValidationError) as exc:
        to_student_normalized(raw)
    assert MOBILE_ERROR in str(exc.value)


def test_to_student_normalized_invalid_national_id() -> None:
    """Invalid national IDs must raise a Persian ``ValueError``."""

    raw = {
        "gender": "زن",
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09123456789",
        "national_id": "12345",
        "school_code": None,
        "mentor_special_schools": [],
    }
    with pytest.raises(ValidationError) as exc:
        to_student_normalized(raw)
    assert NATIONAL_ID_ERROR in str(exc.value)


@given(st.text(alphabet="0123456789۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", min_size=1, max_size=32))
def test_normalize_digits_property(value: str) -> None:
    """Unicode digits must map 1:1 onto ASCII digits."""

    result = normalize_digits(value)
    assert len(result) == len(value)
    assert set(result) <= set("0123456789")


PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


@st.composite
def mobile_variations(draw: st.DrawFn) -> tuple[str, str]:
    """Generate raw/expected pairs for Iranian mobile numbers."""

    tail = draw(st.text(alphabet="0123456789", min_size=9, max_size=9))
    expected = "09" + tail
    prefix = draw(st.sampled_from(["plain", "plus", "double_zero", "country"]))
    if prefix == "plain":
        raw = expected
    elif prefix == "plus":
        raw = "+98" + expected[1:]
    elif prefix == "double_zero":
        raw = "0098" + expected[1:]
    else:
        raw = "98" + expected[1:]

    numeral_system = draw(st.sampled_from(["ascii", "persian", "arabic"]))
    if numeral_system == "persian":
        raw = raw.translate(PERSIAN_DIGITS)
    elif numeral_system == "arabic":
        raw = raw.translate(ARABIC_DIGITS)

    if draw(st.booleans()):
        separator = draw(st.sampled_from([" ", "-", "  ", " - "]))
        raw = separator.join(raw)

    if draw(st.booleans()):
        raw = f"\t{raw}\n"

    return raw, expected


@given(mobile_variations())
def test_normalize_mobile_property(data: tuple[str, str]) -> None:
    """Property-based guarantee for mobile canonicalization."""

    raw, expected = data
    assert normalize_mobile(raw) == expected


def test_student_normalized_model_direct_validation() -> None:
    """Model validators apply when instantiating directly."""

    instance = StudentNormalized.model_validate(
        {
            "gender": "مرد",
            "reg_status": "1",
            "reg_center": "0",
            "mobile": "00989123456789",
            "national_id": "۱۳۳۲۰۷۳۶۸۹",
            "school_code": "200",
            "student_type": 0,
        }
    )
    assert instance.mobile == "09123456789"
    assert instance.school_code == 200
