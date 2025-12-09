from __future__ import annotations

from __future__ import annotations

from typing import Callable

import pandas as pd

from app.core.students.domain_validation import (
    EDUCATION_LEVEL_TOKEN_MAP,
    GRADE_LEVEL_TOKEN_MAP,
    GENDER_TOKEN_MAP,
    GRADUATION_STATUS_TOKEN_MAP,
    QAIssue,
    _normalize_token,
    parse_group_code,
)


class StudentValueCanonicalizer:
    """Canonicalize raw student values into LAW/Technical SSoT domains."""

    def canonicalize(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[QAIssue]]:
        issues: list[QAIssue] = []
        canonical = df.copy()

        canonical["gender_code"], gender_issues = self._map_series(
            canonical.get("gender_code"),
            self._map_gender,
            field="gender_code",
            severity="P1",
            code="student.gender.unknown_token",
            index=canonical.index,
        )
        issues.extend(gender_issues)

        canonical["graduation_status_code"], grad_issues = self._map_series(
            canonical.get("graduation_status_code"),
            self._map_grad_status,
            field="graduation_status_code",
            severity="P1",
            code="student.graduation.unknown_token",
            index=canonical.index,
        )
        issues.extend(grad_issues)

        canonical["education_level"], education_issues = self._map_series(
            canonical.get("education_level"),
            self._map_education_level,
            field="education_level",
            severity="P1",
            code="student.education.unknown_token",
            index=canonical.index,
        )
        issues.extend(education_issues)

        canonical["grade_level"], grade_issues = self._map_series(
            canonical.get("grade_level"),
            self._map_grade_level,
            field="grade_level",
            severity="P1",
            code="student.grade.unknown_token",
            index=canonical.index,
        )
        issues.extend(grade_issues)

        canonical["group_code"], group_issues = self._map_series(
            canonical.get("group_code"),
            self._map_group_code,
            field="group_code",
            severity="P1",
            code="student.group.unknown_token",
            index=canonical.index,
        )
        issues.extend(group_issues)

        return canonical, issues

    def _map_series(
        self,
        series: pd.Series | None,
        mapper: Callable[[object], tuple[object, QAIssue | None]],
        *,
        field: str,
        severity: str,
        code: str,
        index: pd.Index,
    ) -> tuple[pd.Series, list[QAIssue]]:
        if series is None:
            empty = pd.Series(pd.NA, index=index)
            return empty, [
                QAIssue(
                    field=field,
                    severity=severity,
                    code=code,
                    message="Column missing during canonicalization",
                    rule_id=code,
                )
            ]

        values: list[object] = []
        issues: list[QAIssue] = []
        for idx, raw_value in series.items():
            canonical, issue = mapper(raw_value)
            values.append(canonical)
            if issue is not None:
                issues.append(issue)
        return pd.Series(values, index=series.index), issues

    def _map_gender(self, value: object) -> tuple[object, QAIssue | None]:
        if pd.isna(value):
            return pd.NA, None
        key = _normalize_token(value)
        mapped = GENDER_TOKEN_MAP.get(key)
        if mapped is None:
            return pd.NA, QAIssue(
                field="gender_code",
                severity="P1",
                code="student.gender.unknown_token",
                message=f"Unrecognized gender token: {value}",
                rule_id="student.gender.unknown_token",
            )
        return mapped, None

    def _map_grad_status(self, value: object) -> tuple[object, QAIssue | None]:
        if pd.isna(value):
            return pd.NA, None
        key = _normalize_token(value)
        mapped = GRADUATION_STATUS_TOKEN_MAP.get(key)
        if mapped is None:
            return pd.NA, QAIssue(
                field="graduation_status_code",
                severity="P1",
                code="student.graduation.unknown_token",
                message=f"Unrecognized graduation status token: {value}",
                rule_id="student.graduation.unknown_token",
            )
        return mapped, None

    def _map_education_level(self, value: object) -> tuple[object, QAIssue | None]:
        if pd.isna(value):
            return pd.NA, None
        key = _normalize_token(value)
        mapped = EDUCATION_LEVEL_TOKEN_MAP.get(key)
        if mapped is None:
            return pd.NA, QAIssue(
                field="education_level",
                severity="P1",
                code="student.education.unknown_token",
                message=f"Unrecognized education level: {value}",
                rule_id="student.education.unknown_token",
            )
        return mapped, None

    def _map_grade_level(self, value: object) -> tuple[object, QAIssue | None]:
        if pd.isna(value):
            return pd.NA, None
        normalized = _normalize_token(value)
        mapped = GRADE_LEVEL_TOKEN_MAP.get(normalized)
        if mapped is not None:
            return mapped, None
        if normalized.isdigit():
            return normalized, None
        return pd.NA, QAIssue(
            field="grade_level",
            severity="P1",
            code="student.grade.unknown_token",
            message=f"Unrecognized grade level: {value}",
            rule_id="student.grade.unknown_token",
        )

    def _map_group_code(self, value: object) -> tuple[object, QAIssue | None]:
        if pd.isna(value):
            return pd.NA, None
        normalized = _normalize_token(value)
        parsed = parse_group_code(normalized)
        if parsed is None and normalized:
            return normalized, QAIssue(
                field="group_code",
                severity="P1",
                code="student.group.unknown_token",
                message="Unrecognized group_code token",
                rule_id="student.group.unknown_token",
            )
        if not normalized:
            return pd.NA, None
        return parsed.token if parsed else normalized, None
