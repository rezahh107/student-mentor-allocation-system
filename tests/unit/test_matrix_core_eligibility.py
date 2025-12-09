from __future__ import annotations

import pandas as pd
import pytest

from app.core.matrix.eligibility_rules import evaluate_eligibility
from app.core.matrix.matrix_schema import TRACE_STEPS


@pytest.fixture
def mentor_base() -> pd.Series:
    return pd.Series(
        {
            "mentor_id": 1,
            "group_code": 10,
            "gender_code": 1,
            "grad_status_code": 2,
            "center_code": 5,
            "finance_code": 3,
            "school_code": 7,
            "is_active": True,
        }
    )


@pytest.fixture
def student_base() -> pd.Series:
    return pd.Series(
        {
            "student_id": 99,
            "group_code": 10,
            "gender_code": 1,
            "grad_status_code": 2,
            "center_code": 5,
            "finance_code": 3,
            "school_code": 7,
        }
    )


def test_happy_path_eligibility(
    mentor_base: pd.Series, student_base: pd.Series
) -> None:
    result = evaluate_eligibility(mentor_base, student_base)

    assert result.is_eligible is True
    assert result.blocking_reasons == ()
    assert result.qa_flags == ()
    assert result.trace[: len(TRACE_STEPS)] == TRACE_STEPS


def test_gender_mismatch_blocks(
    mentor_base: pd.Series, student_base: pd.Series
) -> None:
    student = student_base.copy()
    student["gender_code"] = 2

    result = evaluate_eligibility(mentor_base, student)

    assert result.is_eligible is False
    assert "gender_mismatch" in result.blocking_reasons


def test_center_wildcard_allows(
    mentor_base: pd.Series, student_base: pd.Series
) -> None:
    mentor = mentor_base.copy()
    mentor["center_code"] = 0

    result = evaluate_eligibility(mentor, student_base)

    assert result.is_eligible is True
    assert result.blocking_reasons == ()


def test_missing_join_key_raises(
    mentor_base: pd.Series, student_base: pd.Series
) -> None:
    incomplete_student = student_base.drop(labels=["center_code"])

    with pytest.raises(ValueError):
        evaluate_eligibility(mentor_base, incomplete_student)

