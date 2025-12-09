from __future__ import annotations

import pandas as pd
import pytest

from app.core.matrix.capacity_gates import evaluate_capacity


def test_capacity_computation_allows() -> None:
    mentor = pd.Series(
        {
            "capacity_limit": 5,
            "assigned_baseline": 1,
            "allocations_new": 1,
        }
    )

    result = evaluate_capacity(mentor)

    expected_remaining = 3
    assert result.remaining_capacity == expected_remaining
    assert result.capacity_blocking is False
    assert result.qa_flags == ()


def test_frozen_mentor_blocks_capacity() -> None:
    mentor = pd.Series(
        {
            "capacity_limit": 2,
            "assigned_baseline": 1,
            "allocations_new": 0,
            "is_frozen": True,
        }
    )

    result = evaluate_capacity(mentor)

    assert result.capacity_blocking is True
    assert "mentor_frozen" in result.qa_flags


def test_negative_remaining_capacity_blocks() -> None:
    mentor = pd.Series(
        {
            "capacity_limit": 1,
            "assigned_baseline": 1,
            "allocations_new": 2,
        }
    )

    result = evaluate_capacity(mentor)

    assert result.capacity_blocking is True
    negative_capacity = -2
    assert result.remaining_capacity == negative_capacity
    assert "remaining_capacity_negative" in result.qa_flags


def test_missing_capacity_field_raises() -> None:
    mentor = pd.Series({"capacity_limit": 1, "assigned_baseline": 1})

    with pytest.raises(ValueError):
        evaluate_capacity(mentor)

