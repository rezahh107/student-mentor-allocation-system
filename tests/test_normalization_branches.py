# --- file: tests/test_normalization_branches.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}

from __future__ import annotations

import json
import logging
from typing import Iterable, List

import pytest

pytest.importorskip(
    "hypothesis",
    reason="DEPENDENCY_MISSING: کتابخانه Hypothesis برای این محیط نصب نشده است.",
)
from hypothesis import given, strategies as st

from src.core.models import (
    Mentor,
    StudentNormalized,
    _normalize_student_type_value,
    to_student_normalized,
)
from src.core.normalize import (
    GENDER_ERROR,
    MOBILE_ERROR,
    NATIONAL_ID_ERROR,
    REG_CENTER_ERROR,
    REG_STATUS_ERROR,
    SCHOOL_CODE_ERROR,
    derive_student_type,
    normalize_gender,
    normalize_int_sequence,
    normalize_mobile,
    normalize_name,
    normalize_national_id,
    normalize_reg_center,
    normalize_reg_status,
    normalize_school_code,
)


def _payloads(caplog: pytest.LogCaptureFixture) -> List[dict[str, object]]:
    """Decode structured logging payloads captured during normalization."""

    decoded: List[dict[str, object]] = []
    for record in caplog.records:
        try:
            payload = json.loads(record.message)
        except json.JSONDecodeError:
            continue
        assert set(payload) == {"code", "sample", "mobile_mask", "nid_hash"}
        decoded.append(payload)
    return decoded


def _codes(caplog: pytest.LogCaptureFixture) -> List[str]:
    return [payload["code"] for payload in _payloads(caplog)]


def _mobile_digit_variant(char: str) -> st.SearchStrategy[str]:
    persian_digits = {"0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴", "5": "۵", "6": "۶", "7": "۷", "8": "۸", "9": "۹"}
    arabic_digits = {"0": "٠", "1": "١", "2": "٢", "3": "٣", "4": "٤", "5": "٥", "6": "٦", "7": "٧", "8": "٨", "9": "٩"}
    return st.sampled_from([char, persian_digits[char], arabic_digits[char]])


@st.composite
def mobile_inputs(draw) -> str:
    digits = f"{draw(st.integers(min_value=100_000_000, max_value=999_999_999)):09d}"
    base = "09" + digits
    prefix = draw(st.sampled_from(["", "+98", "0098", "098", "98"]))
    raw = base if not prefix else prefix + base[1:]
    pieces: list[str] = []
    for char in raw:
        if char.isdigit():
            pieces.append(draw(_mobile_digit_variant(char)))
            pieces.append(draw(st.sampled_from(["", " ", "-", "  "])))
        else:
            pieces.append(char)
            pieces.append(draw(st.sampled_from(["", " "])))
    prefix_pad = draw(st.sampled_from(["", " ", "  "]))
    suffix_pad = draw(st.sampled_from(["", " "]))
    return prefix_pad + "".join(pieces).strip() + suffix_pad


@pytest.mark.parametrize(
    ("func", "value", "message", "code"),
    [
        (normalize_gender, True, GENDER_ERROR, "gender.bool"),
        (normalize_reg_status, False, REG_STATUS_ERROR, "reg_status.bool"),
        (normalize_reg_center, True, REG_CENTER_ERROR, "reg_center.bool"),
        (normalize_mobile, False, MOBILE_ERROR, "mobile.bool"),
        (normalize_school_code, True, SCHOOL_CODE_ERROR, "school_code.bool"),
        (normalize_national_id, False, NATIONAL_ID_ERROR, "national_id.bool"),
    ],
)
def test_boolean_inputs_rejected(
    func, value, message, code, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError) as exc:
            func(value)
    assert str(exc.value) == message
    assert code in _codes(caplog)


@pytest.mark.parametrize(
    "raw",
    ["hakmat", "Hekmat", "حکمت", "حكمت", "حكـمت"],
)
def test_reg_status_variants_map_to_three(raw: str) -> None:
    assert normalize_reg_status(raw) == 3


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("۱", 1), (" 0 ", 0), ("2", 2)],
)
def test_reg_center_valid_examples(raw: str, expected: int) -> None:
    assert normalize_reg_center(raw) == expected


@pytest.mark.parametrize("raw", ["۳", "5", "center", True])
def test_reg_center_invalid_examples(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_reg_center(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+98 912-345-6789", "09123456789"),
        ("00989121234567", "09121234567"),
        ("۹۱۲۳۴۵۶۷۸۹", "09123456789"),
    ],
)
def test_mobile_examples(raw: str, expected: str) -> None:
    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["09123", "08123456789", "0098123"])
def test_mobile_invalid_lengths(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_mobile(raw)


@given(mobile_inputs())
def test_mobile_normalization_is_idempotent(raw: str) -> None:
    normalized = normalize_mobile(raw)
    assert normalize_mobile(normalized) == normalized
    assert normalized.startswith("09")
    assert len(normalized) == 11


@pytest.mark.parametrize("raw", ["2", "foo", None, ""])
def test_reg_status_invalid_inputs(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_reg_status(raw)


@pytest.mark.parametrize("raw", [2, "", None])
def test_gender_invalid_inputs(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_gender(raw)


def test_normalize_name_rtl_rules(caplog: pytest.LogCaptureFixture) -> None:
    raw = "  كاظم‌ ي    زهرا  "
    with caplog.at_level(logging.WARNING):
        assert normalize_name(raw) == "کاظم ی زهرا"
    payloads = _payloads(caplog)
    cleaned = [payload for payload in payloads if payload["code"] == "name.cleaned"]
    assert cleaned
    assert any(payload["code"] == "name.arabic_letters" for payload in payloads)
    sample = cleaned[0]["sample"].strip()
    assert sample.startswith("كاظم") or sample.startswith("کاظم")
    assert normalize_name(None) is None
    with pytest.raises(ValueError):
        normalize_name(True)


def test_normalize_int_sequence_invalid_item_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_int_sequence([101, True])
    assert "mentor_special_schools.item_bool" in _codes(caplog)


def test_normalize_school_code_examples() -> None:
    assert normalize_school_code(" 101 ") == 101
    assert normalize_school_code(None) is None
    with pytest.raises(ValueError):
        normalize_school_code("abc")


def test_normalize_national_id_handles_persian_digits() -> None:
    assert normalize_national_id("۰۰۶۰۳۰۸۶۴۸") == "0060308648"
    with pytest.raises(ValueError) as exc:
        normalize_national_id("۱۲۳۴۵")
    assert str(exc.value) == NATIONAL_ID_ERROR


def test_derive_student_type_with_provider_and_logging(caplog: pytest.LogCaptureFixture) -> None:
    def provider(year: int) -> Iterable[int]:
        if year == 1402:
            return ["bad", 202]
        return []

    with caplog.at_level(logging.WARNING):
        result = derive_student_type(202, [], roster_year=1402, provider=provider)
    assert result == 1
    assert "student_type.provider_invalid" in _codes(caplog)


def test_derive_student_type_without_match() -> None:
    assert derive_student_type(999, [100, 101]) == 0


def test_to_student_normalized_aliases_and_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    raw = {
        "sex": "male",
        "status_reg": "Hakmat",
        "centre": "2",
        "mobile": "+989121234567",
        "national_id": "1332073689",
        "school_code": "101",
        "student_type": 0,
        "mentor_special_schools": ["101"],
    }

    with caplog.at_level(logging.WARNING):
        model = to_student_normalized(raw)
    assert isinstance(model, StudentNormalized)
    assert model.gender == 1
    assert model.reg_status == 3
    assert model.reg_center == 2
    assert model.student_type == 1
    payloads = _payloads(caplog)
    ignored_logs = [payload for payload in payloads if payload["code"] == "student_type.ignored_input"]
    assert ignored_logs
    assert ignored_logs[0]["sample"] == "*"


def test_to_student_normalized_with_provider(caplog: pytest.LogCaptureFixture) -> None:
    def provider(year: int) -> Iterable[int]:
        assert year == 1401
        return frozenset({4040})

    raw = {
        "gender": "زن",
        "reg_status": 1,
        "reg_center": "۰",
        "mobile": "00989123456789",
        "national_id": "۱۳۳۲۰۷۳۶۸۹",
        "school_code": 4040,
        "mentor_special_schools": [],
    }

    with caplog.at_level(logging.WARNING):
        model = to_student_normalized(raw, roster_year=1401, special_school_provider=provider)
    assert model.student_type == 1
    assert _payloads(caplog) == []


def test_student_type_invalid_input_logged(caplog: pytest.LogCaptureFixture) -> None:
    raw = {
        "gender": 0,
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09123456789",
        "national_id": "1332073689",
        "school_code": 101,
        "student_type": "two",
        "mentor_special_schools": [101],
    }

    with caplog.at_level(logging.WARNING):
        model = to_student_normalized(raw)
    assert model.student_type == 1
    assert "student_type.ignored_input" in _codes(caplog)


def test_student_type_bool_input_raises_in_validator() -> None:
    with pytest.raises(ValueError):
        StudentNormalized.model_validate(
            {
                "gender": 0,
                "reg_status": 1,
                "reg_center": 0,
                "mobile": "09123456789",
                "national_id": "1332073689",
                "school_code": 101,
                "student_type": True,
            }
        )


def test_student_type_respects_aliased_data_and_roster(caplog: pytest.LogCaptureFixture) -> None:
    def provider(year: int) -> Iterable[int]:
        return [5001]

    raw = {
        "sex": "زن",
        "status": 0,
        "center": "۱",
        "mobile": "09121234567",
        "national_id": "1332073689",
        "school_code": "5001",
        "mentor_special_schools": [],
    }

    with caplog.at_level(logging.WARNING):
        model = to_student_normalized(raw, roster_year=1400, special_school_provider=provider)
    assert model.student_type == 1
    assert model.reg_status == 0
    assert _payloads(caplog) == []


def test_normalize_int_sequence_type_errors(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_int_sequence("101,102")
    assert "mentor_special_schools.type" in _codes(caplog)


def test_name_warning_for_non_empty_null(caplog: pytest.LogCaptureFixture) -> None:
    raw = {
        "gender": 0,
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09123456789",
        "national_id": "1332073689",
        "school_code": None,
        "name": "   ",
    }

    with caplog.at_level(logging.WARNING):
        to_student_normalized(raw)
    assert "name.empty_after_clean" in _codes(caplog)


def test_to_student_normalized_emits_name_mismatch_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = {
        "gender": "زن",
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09123456789",
        "national_id": "1332073689",
        "school_code": None,
        "mentor_special_schools": [],
        "name": "  كاظم‌ ي    زهرا  ",
    }

    with caplog.at_level(logging.WARNING):
        to_student_normalized(raw)
    codes = _codes(caplog)
    assert "name.cleaned" in codes
    assert "name.arabic_letters" in codes


def test_normalize_school_code_bool_rejected(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_school_code(True)
    assert "school_code.bool" in _codes(caplog)


def test_normalize_reg_center_none(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_reg_center(None)
    assert "reg_center.none" in _codes(caplog)


def test_normalize_mobile_none(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_mobile(None)
    assert "mobile.none" in _codes(caplog)


def test_normalize_int_sequence_root_bool(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_int_sequence(True)
    assert "mentor_special_schools.bool" in _codes(caplog)


def test_normalize_int_sequence_non_iterable(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_int_sequence(5)
    assert "mentor_special_schools.iterable" in _codes(caplog)


def test_normalize_national_id_none(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            normalize_national_id(None)
    assert "national_id.none" in _codes(caplog)


def test_student_remaining_capacity() -> None:
    mentor = Mentor(
        id=1,
        gender=1,
        supported_grades=(7,),
        max_capacity=5,
        current_students=3,
        center_id=1,
    )
    assert mentor.remaining_capacity() == 2


def test_normalize_student_type_value_paths(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValueError):
        _normalize_student_type_value(None)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError):
            _normalize_student_type_value(5)
    assert "student_type.out_of_range" in _codes(caplog)
    assert _normalize_student_type_value(" 1 ") == 1


def test_to_student_normalized_name_bool_logs(caplog: pytest.LogCaptureFixture) -> None:
    raw = {
        "gender": 0,
        "reg_status": 1,
        "reg_center": 0,
        "mobile": "09123456789",
        "national_id": "1332073689",
        "school_code": None,
        "name": True,
    }

    with caplog.at_level(logging.WARNING):
        to_student_normalized(raw)
    payloads = _payloads(caplog)
    assert any(payload["code"] == "name.invalid" for payload in payloads)
