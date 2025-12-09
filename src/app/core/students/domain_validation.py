from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import pandas as pd

from app.core.students.canonical_frame import StudentCanonicalFrame

Severity = str


def _normalize_token(value: object) -> str:
    return str(value).strip().lower()


@dataclass(frozen=True)
class GroupCodeInterpretation:
    token: str
    grade_level: str
    education_level: str


GENDER_TOKEN_MAP: dict[str, int] = {
    "1": 1,
    "01": 1,
    "male": 1,
    "m": 1,
    "boy": 1,
    "پسر": 1,
    "مرد": 1,
    "آقا": 1,
    "2": 2,
    "0": 2,
    "02": 2,
    "female": 2,
    "f": 2,
    "girl": 2,
    "دختر": 2,
    "زن": 2,
    "خانم": 2,
}


GRADUATION_STATUS_TOKEN_MAP: dict[str, int] = {
    "0": 0,
    "current": 0,
    "enrolled": 0,
    "studying": 0,
    "درحال تحصیل": 0,
    "در حال تحصیل": 0,
    "جاری": 0,
    "دانش آموز": 0,
    "student": 0,
    "1": 1,
    "graduated": 1,
    "graduate": 1,
    "فارغ التحصیل": 1,
    "فارغالتحصیل": 1,
    "فارغ‌التحصیل": 1,
    "2": 2,
    "dropped": 2,
    "dropout": 2,
    "ترک تحصیل": 2,
}


EDUCATION_LEVEL_TOKEN_MAP: dict[str, str] = {
    "primary": "primary",
    "elementary": "primary",
    "ابتدایی": "primary",
    "ابتدایى": "primary",
    "middle": "middle",
    "متوسطه اول": "middle",
    "راهنمایی": "middle",
    "راهنمايى": "middle",
    "junior": "middle",
    "high": "high",
    "متوسطه دوم": "high",
    "دبیرستان": "high",
    "نظری": "high",
    "technical": "technical",
    "vocational": "technical",
    "هنرستان": "technical",
}


GRADE_LEVEL_TOKEN_MAP: dict[str, str] = {
    "1": "1",
    "اول": "1",
    "پایه اول": "1",
    "2": "2",
    "دوم": "2",
    "3": "3",
    "سوم": "3",
    "4": "4",
    "چهارم": "4",
    "5": "5",
    "پنجم": "5",
    "6": "6",
    "ششم": "6",
    "7": "7",
    "هفتم": "7",
    "8": "8",
    "هشتم": "8",
    "9": "9",
    "نهم": "9",
    "10": "10",
    "دهم": "10",
    "11": "11",
    "یازدهم": "11",
    "يازده": "11",
    "12": "12",
    "دوازدهم": "12",
}


GROUP_CODE_REFERENCE: dict[str, GroupCodeInterpretation] = {
    token: GroupCodeInterpretation(token=token, grade_level=grade, education_level=education)
    for token, grade, education in (
        ("1", "1", "primary"),
        ("2", "2", "primary"),
        ("3", "3", "primary"),
        ("4", "4", "primary"),
        ("5", "5", "primary"),
        ("6", "6", "primary"),
        ("7", "7", "middle"),
        ("8", "8", "middle"),
        ("9", "9", "middle"),
        ("10", "10", "high"),
        ("11", "11", "high"),
        ("12", "12", "high"),
        ("دهم", "10", "high"),
        ("یازدهم", "11", "high"),
        ("دوازدهم", "12", "high"),
        ("هنرستان", "10", "technical"),
    )
}


def _grade_to_education_level(grade: str) -> str | None:
    try:
        numeric = int(grade)
    except ValueError:
        return None
    if 1 <= numeric <= 6:
        return "primary"
    if 7 <= numeric <= 9:
        return "middle"
    if 10 <= numeric <= 12:
        return "high"
    return None


def parse_group_code(group_code: object) -> GroupCodeInterpretation | None:
    if pd.isna(group_code):
        return None
    token = _normalize_token(group_code)
    if token in GROUP_CODE_REFERENCE:
        return GROUP_CODE_REFERENCE[token]
    mapped_grade = GRADE_LEVEL_TOKEN_MAP.get(token)
    if mapped_grade is None:
        return None
    education_level = _grade_to_education_level(mapped_grade)
    if education_level is None:
        return None
    return GroupCodeInterpretation(
        token=token,
        grade_level=mapped_grade,
        education_level=education_level,
    )


@dataclass(frozen=True)
class QAIssue:
    field: str
    severity: Severity
    code: str
    message: str
    row: int | None = None
    rule_id: str | None = None
    category: str | None = None

    @property
    def can_continue(self) -> bool:
        return self.severity != "P0"

    def as_dict(self) -> dict[str, object]:
        rule_id = self.rule_id or self.code
        return {
            "field": self.field,
            "severity": self.severity,
            "code": self.code,
            "rule_id": rule_id,
            "message": self.message,
            "row": self.row,
            "category": self.category,
            "can_continue": self.can_continue,
        }


class StudentDomainValidator:
    REQUIRED_JOIN_FIELDS: tuple[str, ...] = (
        "gender_code",
        "group_code",
    )

    def validate(self, frame: StudentCanonicalFrame) -> tuple[list[QAIssue], bool]:
        issues: list[QAIssue] = []
        df = frame.frame

        issues.extend(self._validate_required_fields(df))
        issues.extend(self._validate_gender(df))
        issues.extend(self._validate_graduation_status(df))
        issues.extend(self._validate_levels(df))

        can_continue = all(issue.can_continue for issue in issues)
        return issues, can_continue

    def _validate_required_fields(self, df: pd.DataFrame) -> list[QAIssue]:
        issues: list[QAIssue] = []
        for field in self.REQUIRED_JOIN_FIELDS:
            if field not in df.columns:
                issues.append(
                    QAIssue(
                        field=field,
                        severity="P0",
                        code="student.required.missing_field",
                        message=f"Missing required join field: {field}",
                        rule_id="student.required.missing_field",
                    )
                )
                continue
            series = df[field]
            if series.isna().all():
                issues.append(
                    QAIssue(
                        field=field,
                        severity="P0",
                        code="student.required.empty_field",
                        message=f"Missing required join field: {field}",
                        rule_id="student.required.empty_field",
                    )
                )
            for idx, value in series.items():
                if pd.isna(value):
                    issues.append(
                        QAIssue(
                            field=field,
                            severity="P0",
                            code="student.required.row_missing",
                            message="Row is missing join-critical value",
                            row=int(idx),
                            rule_id="student.required.row_missing",
                        )
                    )
        return issues

    def _validate_gender(self, df: pd.DataFrame) -> list[QAIssue]:
        issues: list[QAIssue] = []
        if "gender_code" not in df.columns:
            return issues
        allowed = set(GENDER_TOKEN_MAP.values())
        for idx, value in df["gender_code"].items():
            if pd.isna(value):
                issues.append(
                    QAIssue(
                        field="gender_code",
                        severity="P0",
                        code="student.gender.missing",
                        message="Missing gender value",
                        row=int(idx),
                        rule_id="student.gender.missing",
                    )
                )
                continue
            if value not in allowed:
                issues.append(
                    QAIssue(
                        field="gender_code",
                        severity="P0",
                        code="student.gender.invalid",
                        message=f"Invalid gender code: {value}",
                        row=int(idx),
                        rule_id="student.gender.invalid",
                    )
                )
        return issues

    def _validate_graduation_status(self, df: pd.DataFrame) -> list[QAIssue]:
        issues: list[QAIssue] = []
        if "graduation_status_code" not in df.columns:
            return issues
        allowed = set(GRADUATION_STATUS_TOKEN_MAP.values())
        for idx, value in df["graduation_status_code"].items():
            if pd.isna(value):
                issues.append(
                    QAIssue(
                        field="graduation_status_code",
                        severity="P1",
                        code="student.graduation.missing",
                        message="Missing graduation status",
                        row=int(idx),
                        rule_id="student.graduation.missing",
                    )
                )
            elif value not in allowed:
                issues.append(
                    QAIssue(
                        field="graduation_status_code",
                        severity="P1",
                        code="student.graduation.invalid",
                        message=f"Invalid graduation status: {value}",
                        row=int(idx),
                        rule_id="student.graduation.invalid",
                    )
                )
        return issues

    def _validate_levels(self, df: pd.DataFrame) -> list[QAIssue]:
        issues: list[QAIssue] = []
        education_levels = df.get("education_level")
        grade_levels = df.get("grade_level")
        group_codes = df.get("group_code")

        if education_levels is None or grade_levels is None or group_codes is None:
            return issues

        education_levels = education_levels.fillna("")
        grade_levels = grade_levels.fillna("")
        group_codes = group_codes.fillna("")

        allowed_education = set(EDUCATION_LEVEL_TOKEN_MAP.values())
        allowed_grade = set(GRADE_LEVEL_TOKEN_MAP.values())

        for idx, level in education_levels.items():
            if level and level not in allowed_education:
                issues.append(
                    QAIssue(
                        field="education_level",
                        severity="P1",
                        code="student.education.invalid",
                        message=f"Unknown education level: {level}",
                        row=int(idx),
                        rule_id="student.education.invalid",
                    )
                )
        for idx, level in grade_levels.items():
            if level and level not in allowed_grade:
                issues.append(
                    QAIssue(
                        field="grade_level",
                        severity="P1",
                        code="student.grade.invalid",
                        message=f"Unknown grade level: {level}",
                        row=int(idx),
                        rule_id="student.grade.invalid",
                    )
                )

        for idx, (education_level, grade_level, group_code) in zip(
            education_levels.index, education_levels, grade_levels, group_codes
        ):
            parsed = parse_group_code(group_code)
            if group_code and parsed is None:
                issues.append(
                    QAIssue(
                        field="group_code",
                        severity="P1",
                        code="student.group.unknown",
                        message="Unrecognized group_code token",
                        row=int(idx),
                        rule_id="student.group.unknown",
                    )
                )
                continue
            if grade_level and parsed and grade_level != parsed.grade_level:
                issues.append(
                    QAIssue(
                        field="grade_level",
                        severity="P1",
                        code="student.group.grade_mismatch",
                        message="Grade level conflicts with group_code",
                        row=int(idx),
                        rule_id="student.group.grade_mismatch",
                    )
                )
            expected_education = parsed.education_level if parsed else _grade_to_education_level(
                grade_level
            )
            if education_level and expected_education and education_level != expected_education:
                issues.append(
                    QAIssue(
                        field="education_level",
                        severity="P1",
                        code="student.group.education_mismatch",
                        message="Education level conflicts with group_code",
                        row=int(idx),
                        rule_id="student.group.education_mismatch",
                    )
                )
        return issues


def validate_student_domains(
    frame: StudentCanonicalFrame,
    *,
    validators: Sequence[StudentDomainValidator] | None = None,
) -> tuple[list[QAIssue], bool]:
    used_validators: Iterable[StudentDomainValidator]
    if validators is None:
        used_validators = (StudentDomainValidator(),)
    else:
        used_validators = validators

    all_issues: list[QAIssue] = []
    can_continue = True
    for validator in used_validators:
        issues, validator_can_continue = validator.validate(frame)
        all_issues.extend(issues)
        can_continue = can_continue and validator_can_continue
    return all_issues, can_continue
