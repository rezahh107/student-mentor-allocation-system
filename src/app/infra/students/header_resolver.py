from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from app.core.students.domain_validation import QAIssue


STUDENT_HEADER_REGISTRY: dict[str, tuple[str, ...]] = {
    "student_id": ("student_id", "id", "studentid", "شناسه"),
    "national_id": ("national id", "national_id", "کد ملی", "ssn"),
    "first_name": ("first name", "first_name", "نام", "fname"),
    "last_name": ("last name", "last_name", "نام خانوادگی", "lname"),
    "gender_code": ("gender", "sex", "جنسیت"),
    "graduation_status_code": (
        "graduation status",
        "graduation_status",
        "وضعیت فارغ التحصیلی",
    ),
    "education_level": ("education level", "education_level", "مقطع"),
    "grade_level": ("grade", "grade_level", "پایه"),
    "group_code": ("group", "group_code", "گروه"),
}


@dataclass
class HeaderPipelineV3:
    registry: dict[str, tuple[str, ...]]

    def resolve(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[QAIssue]]:
        issues: list[QAIssue] = []
        rename: dict[str, str] = {}
        seen: set[str] = set()

        lookup = self._build_lookup(self.registry)
        for column in df.columns:
            normalized = self._normalize(column)
            canonical = lookup.get(normalized)
            if canonical is None:
                issues.append(
                    QAIssue(
                        field=column,
                        severity="P2",
                        code="student.header.unknown",
                        message="Unrecognized column header",
                    )
                )
                continue
            if canonical in seen:
                issues.append(
                    QAIssue(
                        field=canonical,
                        severity="P1",
                        code="student.header.duplicate",
                        message="Duplicate column for canonical field",
                    )
                )
                continue
            rename[column] = canonical
            seen.add(canonical)

        resolved = df.rename(columns=rename)
        return resolved, issues

    @staticmethod
    def _build_lookup(registry: dict[str, tuple[str, ...]]) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for canonical, aliases in registry.items():
            for alias in aliases:
                lookup[HeaderPipelineV3._normalize(alias)] = canonical
        return lookup

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().lower()

    def aliases(self, field: str) -> Iterable[str]:
        return self.registry.get(field, ())


class StudentHeaderResolver:
    """Thin adapter that configures HeaderPipelineV3 for student imports."""

    def __init__(self, pipeline: HeaderPipelineV3 | None = None) -> None:
        self._pipeline = pipeline or HeaderPipelineV3(STUDENT_HEADER_REGISTRY)

    @property
    def registry(self) -> dict[str, tuple[str, ...]]:
        return self._pipeline.registry

    def resolve(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[QAIssue]]:
        return self._pipeline.resolve(df)

    def aliases(self, field: str) -> Iterable[str]:
        return self._pipeline.aliases(field)
