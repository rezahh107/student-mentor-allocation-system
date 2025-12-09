from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import pandas as pd

JOIN_KEY_COLUMNS: tuple[str, ...] = (
    "group_code",
    "gender_code",
    "grad_status_code",
    "center_code",
    "finance_code",
    "school_code",
)

CAPACITY_COLUMNS: tuple[str, ...] = (
    "capacity_limit",
    "assigned_baseline",
    "allocations_new",
    "total_allocations",
    "remaining_capacity",
)

TRACE_STEPS: tuple[str, ...] = (
    "type",
    "group",
    "gender",
    "graduation_status",
    "center",
    "finance",
    "school",
    "capacity_gate",
)


@dataclass(frozen=True)
class MatrixRow:
    mentor_id: int
    student_id: int
    group_code: int
    gender_code: int
    grad_status_code: int
    center_code: int
    finance_code: int
    school_code: int
    capacity_limit: int
    assigned_baseline: int
    allocations_new: int
    total_allocations: int
    remaining_capacity: int
    is_eligible: bool
    capacity_blocking: bool
    qa_flags: tuple[str, ...]
    trace: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "mentor_id": self.mentor_id,
            "student_id": self.student_id,
            "group_code": self.group_code,
            "gender_code": self.gender_code,
            "grad_status_code": self.grad_status_code,
            "center_code": self.center_code,
            "finance_code": self.finance_code,
            "school_code": self.school_code,
            "capacity_limit": self.capacity_limit,
            "assigned_baseline": self.assigned_baseline,
            "allocations_new": self.allocations_new,
            "total_allocations": self.total_allocations,
            "remaining_capacity": self.remaining_capacity,
            "is_eligible": self.is_eligible,
            "capacity_blocking": self.capacity_blocking,
            "qa_flags": self.qa_flags,
            "trace": self.trace,
        }


class MatrixSchema:
    """Utility helpers for validating MatrixCore DataFrame payloads."""

    @staticmethod
    def required_columns() -> Iterable[str]:
        yield from (
            "mentor_id",
            "student_id",
            *JOIN_KEY_COLUMNS,
            *CAPACITY_COLUMNS,
            "is_eligible",
            "capacity_blocking",
            "qa_flags",
            "trace",
        )

    @classmethod
    def ensure_schema(cls, df: pd.DataFrame) -> pd.DataFrame:
        filled = df.copy()
        for column in cls.required_columns():
            if column not in filled.columns:
                filled[column] = pd.NA
        return filled

    @staticmethod
    def validate_trace(trace: Sequence[str]) -> bool:
        return tuple(trace) == TRACE_STEPS or len(trace) == len(TRACE_STEPS)

