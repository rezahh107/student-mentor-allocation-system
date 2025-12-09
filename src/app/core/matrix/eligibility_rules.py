from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.core.matrix.matrix_schema import JOIN_KEY_COLUMNS, TRACE_STEPS


@dataclass(frozen=True)
class EligibilityResult:
    is_eligible: bool
    qa_flags: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    trace: tuple[str, ...]

    def can_continue(self) -> bool:
        return self.is_eligible and not self.blocking_reasons


def _ensure_join_keys(series: pd.Series) -> None:
    missing = [column for column in JOIN_KEY_COLUMNS if column not in series]
    if missing:
        missing_keys = ", ".join(missing)
        raise ValueError(  # noqa: TRY003
            f"Missing required join keys: {missing_keys}"
        )


def evaluate_eligibility(mentor: pd.Series, student: pd.Series) -> EligibilityResult:
    _ensure_join_keys(mentor)
    _ensure_join_keys(student)

    blocking_reasons: list[str] = []
    qa_flags: list[str] = []

    steps: list[str] = list(TRACE_STEPS)

    if not bool(mentor.get("is_active", True)):
        blocking_reasons.append("mentor_inactive")
        steps[0] = "type:inactive"

    if mentor["group_code"] != student["group_code"]:
        blocking_reasons.append("group_mismatch")
        steps[1] = "group:blocked"

    mentor_gender = int(mentor["gender_code"])
    student_gender = int(student["gender_code"])
    if mentor_gender not in (0, student_gender):
        blocking_reasons.append("gender_mismatch")
        steps[2] = "gender:blocked"

    mentor_grad = int(mentor["grad_status_code"])
    student_grad = int(student["grad_status_code"])
    if mentor_grad not in (0, student_grad):
        blocking_reasons.append("graduation_status_mismatch")
        steps[3] = "graduation_status:blocked"

    mentor_center = int(mentor["center_code"])
    student_center = int(student["center_code"])
    if mentor_center not in (0, student_center):
        blocking_reasons.append("center_mismatch")
        steps[4] = "center:blocked"

    if int(mentor["finance_code"]) != int(student["finance_code"]):
        blocking_reasons.append("finance_mismatch")
        steps[5] = "finance:blocked"

    mentor_school = int(mentor["school_code"])
    student_school = int(student["school_code"])
    if mentor_school not in (0, student_school):
        qa_flags.append("school_mismatch_soft")
        steps[6] = "school:soft"

    is_eligible = not blocking_reasons
    return EligibilityResult(
        is_eligible=is_eligible,
        qa_flags=tuple(qa_flags),
        blocking_reasons=tuple(blocking_reasons),
        trace=tuple(steps),
    )

