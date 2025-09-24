# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from src.phase2_counter_service import validation
from src.phase2_counter_service.errors import CounterServiceError


def test_ensure_valid_inputs_normalizes():
    nid, year = validation.ensure_valid_inputs("  ۱۲۳۴۵۶۷۸۹۰", 0, " 25 ")
    assert nid == "1234567890"
    assert year == "25"


def test_ensure_valid_inputs_invalid_gender():
    with pytest.raises(CounterServiceError) as exc:
        validation.ensure_valid_inputs("1234567890", 7, "25")
    assert exc.value.detail.code == "E_INVALID_GENDER"


def test_ensure_valid_inputs_invalid_year():
    with pytest.raises(CounterServiceError) as exc:
        validation.ensure_valid_inputs("1234567890", 0, "2x")
    assert exc.value.detail.code == "E_YEAR_CODE_INVALID"


def test_ensure_counter_format_enforces_regex():
    with pytest.raises(CounterServiceError) as exc:
        validation.ensure_counter_format("99374000")
    assert exc.value.detail.code == "E_COUNTER_EXHAUSTED"


@given(st.text())
def test_normalize_idempotent(text: str) -> None:
    normalized = validation.normalize(text)
    assert validation.normalize(normalized) == normalized
