from __future__ import annotations

import pandas as pd
import pytest

from app.core.matrix.build_matrix_core import build_matrix_core
from app.core.matrix.matrix_schema import (
    CAPACITY_COLUMNS,
    JOIN_KEY_COLUMNS,
    TRACE_STEPS,
)


@pytest.fixture
def mentor_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "mentor_id": 1,
                "group_code": 10,
                "gender_code": 1,
                "grad_status_code": 2,
                "center_code": 5,
                "finance_code": 3,
                "school_code": 7,
                "capacity_limit": 3,
                "assigned_baseline": 1,
                "allocations_new": 0,
                "is_active": True,
            },
            {
                "mentor_id": 2,
                "group_code": 10,
                "gender_code": 1,
                "grad_status_code": 2,
                "center_code": 5,
                "finance_code": 3,
                "school_code": 7,
                "capacity_limit": 1,
                "assigned_baseline": 1,
                "allocations_new": 0,
                "is_active": True,
            },
        ]
    )


@pytest.fixture
def student_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "student_id": 100,
                "group_code": 10,
                "gender_code": 1,
                "grad_status_code": 2,
                "center_code": 5,
                "finance_code": 3,
                "school_code": 7,
            },
            {
                "student_id": 200,
                "group_code": 10,
                "gender_code": 1,
                "grad_status_code": 2,
                "center_code": 5,
                "finance_code": 3,
                "school_code": 7,
            },
        ]
    )


def test_matrix_builds_and_orders(
    mentor_frame: pd.DataFrame, student_frame: pd.DataFrame
) -> None:
    matrix = build_matrix_core(mentor_frame, student_frame)

    assert list(matrix.columns[: len(JOIN_KEY_COLUMNS)])
    assert {"mentor_id", "student_id"}.issubset(matrix.columns)
    assert set(CAPACITY_COLUMNS).issubset(matrix.columns)

    expected_rows = 2
    assert len(matrix) == expected_rows
    assert matrix.loc[0, "remaining_capacity"] >= matrix.loc[1, "remaining_capacity"]
    assert matrix["trace"].apply(lambda trace: len(trace) == len(TRACE_STEPS)).all()


def test_capacity_gate_blocks_full_mentor(
    mentor_frame: pd.DataFrame, student_frame: pd.DataFrame
) -> None:
    matrix = build_matrix_core(mentor_frame, student_frame)

    full_capacity_id = 2
    assert (matrix["mentor_id"] == full_capacity_id).sum() == 0


def test_missing_join_key_fails_fast(
    mentor_frame: pd.DataFrame, student_frame: pd.DataFrame
) -> None:
    broken_students = student_frame.drop(columns=["group_code"])

    with pytest.raises(ValueError):
        build_matrix_core(mentor_frame, broken_students)

