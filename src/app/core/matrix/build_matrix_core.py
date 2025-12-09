from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from app.core.matrix.capacity_gates import CapacityResult, evaluate_capacity
from app.core.matrix.eligibility_rules import EligibilityResult, evaluate_eligibility
from app.core.matrix.matrix_schema import (
    CAPACITY_COLUMNS,
    JOIN_KEY_COLUMNS,
    MatrixSchema,
)


def _assert_columns(frame: pd.DataFrame, required: Iterable[str], role: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ValueError(f"Missing {role} field(s): {missing_fields}")  # noqa: TRY003


def _validate_canonical_inputs(
    mentor_frame: pd.DataFrame, student_frame: pd.DataFrame
) -> None:
    mentor_fields: tuple[str, ...] = (
        "mentor_id",
        *JOIN_KEY_COLUMNS,
        *CAPACITY_COLUMNS[:3],
    )
    student_fields: tuple[str, ...] = ("student_id", *JOIN_KEY_COLUMNS)

    _assert_columns(mentor_frame, mentor_fields, "mentor")
    _assert_columns(student_frame, student_fields, "student")


def _merge_candidates(
    mentor_frame: pd.DataFrame, student_frame: pd.DataFrame
) -> pd.DataFrame:
    return mentor_frame.merge(
        student_frame,
        on=list(JOIN_KEY_COLUMNS),
        suffixes=("_mentor", "_student"),
    )


def build_matrix_core(
    mentor_frame: pd.DataFrame, student_frame: pd.DataFrame
) -> pd.DataFrame:
    _validate_canonical_inputs(mentor_frame, student_frame)

    merged = _merge_candidates(mentor_frame, student_frame)
    rows: list[dict[str, object]] = []

    for _, row in merged.iterrows():
        mentor_fields = {
            "mentor_id": int(row["mentor_id"]),
            **{key: int(row[key]) for key in JOIN_KEY_COLUMNS},
            "capacity_limit": int(row["capacity_limit"]),
            "assigned_baseline": int(row.get("assigned_baseline", 0)),
            "allocations_new": int(row.get("allocations_new", 0)),
            "is_active": row.get("is_active", True),
            "is_frozen": row.get("is_frozen", False),
        }
        mentor = pd.Series(mentor_fields)

        student_fields = {
            "student_id": int(row["student_id"]),
            **{key: int(row[key]) for key in JOIN_KEY_COLUMNS},
        }
        student = pd.Series(student_fields)

        eligibility: EligibilityResult = evaluate_eligibility(mentor, student)
        if not eligibility.is_eligible:
            continue

        capacity: CapacityResult = evaluate_capacity(mentor)
        trace = list(eligibility.trace)
        trace[-1] = (
            "capacity_gate:blocked"
            if capacity.capacity_blocking
            else "capacity_gate:pass"
        )

        qa_flags = (*eligibility.qa_flags, *capacity.qa_flags)

        matrix_row = {
            "mentor_id": int(mentor["mentor_id"]),
            "student_id": int(student["student_id"]),
            **{key: int(mentor[key]) for key in JOIN_KEY_COLUMNS},
            "capacity_limit": int(mentor["capacity_limit"]),
            "assigned_baseline": int(mentor.get("assigned_baseline", 0)),
            "allocations_new": int(mentor.get("allocations_new", 0)),
            "total_allocations": capacity.total_allocations,
            "remaining_capacity": capacity.remaining_capacity,
            "is_eligible": eligibility.is_eligible,
            "capacity_blocking": capacity.capacity_blocking,
            "qa_flags": tuple(qa_flags),
            "trace": tuple(trace),
        }

        if capacity.can_allocate():
            rows.append(matrix_row)

    matrix_df = pd.DataFrame(rows)
    if not matrix_df.empty:
        matrix_df = matrix_df.sort_values(
            by=["remaining_capacity", "allocations_new", "mentor_id"],
            ascending=[False, True, True],
        ).reset_index(drop=True)

    return MatrixSchema.ensure_schema(matrix_df)

