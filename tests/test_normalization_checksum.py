# --- file: tests/test_normalization_checksum.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}

from __future__ import annotations

import logging

import pytest

pytest.importorskip(
    "hypothesis",
    reason="DEPENDENCY_MISSING: کتابخانه Hypothesis برای این محیط نصب نشده است.",
)
from hypothesis import given, strategies as st

from sma.core.normalize import (
    MOBILE_ERROR,
    NATIONAL_ID_ERROR,
    normalize_digits,
    normalize_mobile,
    normalize_national_id,
)


_VALID_IDS = (
    ("1332073689", "1332073689"),
    ("۰۰۶۰۳۰۸۶۴۸", "0060308648"),
    ("٦٨١٨٧٦٣٣٨٣", "6818763383"),
)

_INVALID_CHECKSUM_IDS = (
    "1332073688",
    "۰۰۶۰۳۰۸۶۴۷",
    "٦٨١٨٧٦٣٣٨٤",
)


@pytest.mark.parametrize(("value", "expected"), _VALID_IDS)
def test_normalize_national_id_valid_examples(value: str, expected: str) -> None:
    """Verify checksum and digit normalization for canonical Iranian IDs."""

    assert normalize_national_id(value) == expected


@pytest.mark.parametrize("value", _INVALID_CHECKSUM_IDS)
def test_normalize_national_id_checksum_failure(value: str, caplog: pytest.LogCaptureFixture) -> None:
    """Ensure checksum mismatches raise canonical Persian messages and log warnings."""

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError) as exc:
            normalize_national_id(value)
    assert str(exc.value) == NATIONAL_ID_ERROR
    assert "national_id.checksum" in caplog.text


@pytest.mark.parametrize("value", ["123456789", "12345678901", "abcdefghij"])
def test_normalize_national_id_length_failures(value: str) -> None:
    """Reject inputs that are not exactly 10 ASCII digits after cleanup."""

    with pytest.raises(ValueError) as exc:
        normalize_national_id(value)
    assert str(exc.value) == NATIONAL_ID_ERROR


@pytest.mark.parametrize("value", [True, False])
def test_normalize_national_id_boolean_failure(value: bool) -> None:
    """Reject boolean inputs with the canonical Persian message."""

    with pytest.raises(ValueError) as exc:
        normalize_national_id(value)
    assert str(exc.value) == NATIONAL_ID_ERROR


@given(
    st.text(
        alphabet=list("0123456789۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"),
        min_size=1,
        max_size=20,
    )
)
def test_normalize_digits_outputs_ascii(text: str) -> None:
    """Property-based check ensuring digits normalization strips RTL variants."""

    normalized = normalize_digits(text)
    assert all("0" <= ch <= "9" or not ch.isdigit() for ch in normalized)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("98-912-345-6789", "09123456789"),
        ("0989123456789", "09123456789"),
        ("9123456789", "09123456789"),
    ],
)
def test_normalize_mobile_additional_prefixes(raw: str, expected: str) -> None:
    """Cover remaining prefix variants required by the spec."""

    assert normalize_mobile(raw) == expected


@pytest.mark.parametrize("value", [True, False])
def test_normalize_mobile_boolean_failure(value: bool) -> None:
    """Boolean mobile inputs must raise the canonical message."""

    with pytest.raises(ValueError) as exc:
        normalize_mobile(value)
    assert str(exc.value) == MOBILE_ERROR


@given(
    st.builds(
        lambda digits: "09" + digits,
        st.text(alphabet="0123456789", min_size=9, max_size=9),
    )
)
def test_normalize_mobile_idempotent_property(value: str) -> None:
    """Applying normalization twice should yield the same output."""

    first = normalize_mobile(value)
    assert normalize_mobile(first) == first
