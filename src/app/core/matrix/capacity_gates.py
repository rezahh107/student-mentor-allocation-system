from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.matrix.matrix_schema import CAPACITY_COLUMNS


@dataclass(frozen=True)
class CapacityResult:
    remaining_capacity: int
    total_allocations: int
    capacity_blocking: bool
    qa_flags: tuple[str, ...]

    def can_allocate(self) -> bool:
        return not self.capacity_blocking and self.remaining_capacity > 0


def _ensure_capacity_fields(series: pd.Series) -> None:
    missing = [column for column in CAPACITY_COLUMNS[:3] if column not in series]
    if missing:
        missing_fields = ", ".join(sorted(missing))
        raise ValueError(f"Missing capacity fields: {missing_fields}")  # noqa: TRY003


def evaluate_capacity(mentor: pd.Series) -> CapacityResult:
    _ensure_capacity_fields(mentor)

    capacity_limit = int(mentor["capacity_limit"])
    assigned_baseline = int(mentor.get("assigned_baseline", 0))
    allocations_new = int(mentor.get("allocations_new", 0))

    total_allocations = assigned_baseline + allocations_new
    remaining_capacity = capacity_limit - total_allocations

    qa_flags: list[str] = []
    capacity_blocking = False

    if mentor.get("is_frozen", False):
        capacity_blocking = True
        qa_flags.append("mentor_frozen")

    if capacity_limit < 0:
        capacity_blocking = True
        qa_flags.append("capacity_limit_negative")

    if remaining_capacity < 0:
        capacity_blocking = True
        qa_flags.append("remaining_capacity_negative")

    return CapacityResult(
        remaining_capacity=remaining_capacity,
        total_allocations=total_allocations,
        capacity_blocking=capacity_blocking,
        qa_flags=tuple(qa_flags),
    )

