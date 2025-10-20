"""Eligibility policy applying rule engine logic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from .contracts import (
    AllocationConfig,
    MentorLike,
    NormalizedMentor,
    NormalizedStudent,
    StudentLike,
    TraceEntry,
)
from .providers import ManagerCentersProvider, SpecialSchoolsProvider
from .rules import (
    ALL_RULES,
    ManagerCenterGateRule,
    Rule,
    RuleResult,
)

PERSIAN_DIGITS = {
    "۰": "0",
    "٠": "0",
    "١": "1",
    "۱": "1",
    "۲": "2",
    "٢": "2",
    "۳": "3",
    "٣": "3",
    "۴": "4",
    "٤": "4",
    "۵": "5",
    "٥": "5",
    "۶": "6",
    "٦": "6",
    "۷": "7",
    "٧": "7",
    "۸": "8",
    "٨": "8",
    "۹": "9",
    "٩": "9",
}
ZERO_WIDTH_CHARS = {"\u200c", "\u200f", "\u200e", "\ufeff"}


class NormalizationError(ValueError):
    """Raised when data normalization fails."""

    def __init__(self, rule_code: str, message: str, details: dict[str, object]):
        super().__init__(message)
        self.rule_code = rule_code
        self.details = details


def _normalize_text(value: object) -> str:
    text = str(value) if value is not None else ""
    text = text.strip()
    for char in ZERO_WIDTH_CHARS:
        text = text.replace(char, "")
    text = text.replace("ك", "ک").replace("ي", "ی")
    if any(char in PERSIAN_DIGITS for char in text):
        folded = []
        for char in text:
            folded.append(PERSIAN_DIGITS.get(char, char))
        text = "".join(folded)
    return text


def _normalize_int(
    value: object,
    *,
    rule_code: str,
    field_name: str,
    allow_none: bool = False,
    default: int | None = None,
) -> int | None:
    if value is None:
        if allow_none:
            return default
        raise NormalizationError(
            rule_code,
            f"مقدار {field_name} نامعتبر است.",
            {"field": field_name, "value": value},
        )
    text = _normalize_text(value)
    if not text:
        if allow_none:
            return default
        raise NormalizationError(
            rule_code,
            f"مقدار {field_name} خالی است.",
            {"field": field_name},
        )
    try:
        return int(text)
    except ValueError as exc:
        raise NormalizationError(
            rule_code,
            f"امکان تبدیل {field_name} به عدد وجود ندارد.",
            {"field": field_name, "value": text},
        ) from exc


def _normalize_bool(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _normalize_text(value)
    if text.lower() in {"true", "1", "yes", "y", "on"}:
        return True
    if text.lower() in {"false", "0", "no", "n", "off"}:
        return False
    raise NormalizationError(
        "CAPACITY_AVAILABLE",
        f"مقدار بولی {field_name} قابل تفسیر نیست.",
        {"field": field_name, "value": value},
    )


def _normalize_enum(
    value: object,
    *,
    rule_code: str,
    field_name: str,
    allowed: Sequence[int],
) -> int:
    numeric = _normalize_int(value, rule_code=rule_code, field_name=field_name)
    if numeric not in allowed:
        raise NormalizationError(
            rule_code,
            f"مقدار {field_name} خارج از مقادیر مجاز است.",
            {"field": field_name, "value": numeric, "allowed": list(allowed)},
        )
    return numeric


def _normalize_optional_enum(
    value: object,
    *,
    rule_code: str,
    field_name: str,
    allowed: Sequence[int],
    default: int,
) -> int:
    if value is None:
        return default
    text = _normalize_text(value)
    if not text:
        return default
    numeric = _normalize_int(value, rule_code=rule_code, field_name=field_name)
    if numeric not in allowed:
        raise NormalizationError(
            rule_code,
            f"مقدار {field_name} خارج از مقادیر مجاز است.",
            {"field": field_name, "value": numeric, "allowed": list(allowed)},
        )
    return numeric


@dataclass
class EligibilityPolicy:
    """Evaluate mentors against allocation policy rules."""

    special_schools_provider: SpecialSchoolsProvider
    manager_centers_provider: ManagerCentersProvider
    config: AllocationConfig = field(default_factory=AllocationConfig)
    _rules: Sequence[Rule] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        rules: list[Rule] = list(ALL_RULES)
        rules.append(ManagerCenterGateRule(self.manager_centers_provider))
        self._rules = tuple(rules)

    def normalize_student(self, student: StudentLike) -> NormalizedStudent:
        warnings: set[str] = set()
        gender = _normalize_enum(
            student.gender,
            rule_code="GENDER_MATCH",
            field_name="gender",
            allowed=(0, 1),
        )
        group_code = _normalize_text(student.group_code)
        if not group_code:
            raise NormalizationError(
                "GROUP_ALLOWED",
                "کد گروه دانش‌آموز خالی است.",
                {"field": "group_code"},
            )
        reg_center = _normalize_enum(
            student.reg_center,
            rule_code="CENTER_ALLOWED",
            field_name="reg_center",
            allowed=(0, 1, 2),
        )
        reg_status = _normalize_enum(
            student.reg_status,
            rule_code="REG_STATUS_ALLOWED",
            field_name="reg_status",
            allowed=(0, 1, 3),
        )
        edu_status = _normalize_int(
            student.edu_status,
            rule_code="GRADUATE_NOT_TO_SCHOOL",
            field_name="edu_status",
            allow_none=True,
            default=0,
        )
        school_code = _normalize_int(
            student.school_code,
            rule_code="SCHOOL_TYPE_COMPATIBLE",
            field_name="school_code",
            allow_none=True,
        )
        roster_year = _normalize_int(
            getattr(student, "roster_year", None),
            rule_code="SCHOOL_TYPE_COMPATIBLE",
            field_name="roster_year",
            allow_none=True,
        )
        provided_type = _normalize_optional_enum(
            getattr(student, "student_type", None),
            rule_code="SCHOOL_TYPE_COMPATIBLE",
            field_name="student_type",
            allowed=(0, 1),
            default=0,
        )
        derived_type = self._derive_student_type(roster_year, school_code)
        if derived_type is None:
            student_type = provided_type
        else:
            student_type = derived_type
            if provided_type != derived_type:
                warnings.add("student_type_mismatch_roster")
        return NormalizedStudent(
            gender=gender,
            group_code=group_code,
            reg_center=reg_center,
            reg_status=reg_status,
            edu_status=edu_status or 0,
            school_code=school_code,
            student_type=student_type,
            roster_year=roster_year,
            warnings=frozenset(warnings),
        )

    def _derive_student_type(
        self, roster_year: int | None, school_code: int | None
    ) -> int | None:
        if roster_year is None or school_code is None:
            return None
        schools = self.special_schools_provider.get(roster_year)
        if schools is None:
            return None
        return 1 if school_code in schools else 0

    def normalize_mentor(self, mentor: MentorLike) -> NormalizedMentor:
        mentor_id = _normalize_int(
            mentor.mentor_id,
            rule_code="CAPACITY_AVAILABLE",
            field_name="mentor_id",
        )
        gender = _normalize_enum(
            mentor.gender,
            rule_code="GENDER_MATCH",
            field_name="mentor_gender",
            allowed=(0, 1),
        )
        allowed_groups = frozenset(_normalize_text(value) for value in mentor.allowed_groups)
        allowed_centers = frozenset(
            _normalize_enum(
                value,
                rule_code="CENTER_ALLOWED",
                field_name="allowed_center",
                allowed=(0, 1, 2),
            )
            for value in mentor.allowed_centers
        )
        capacity = _normalize_int(
            mentor.capacity,
            rule_code="CAPACITY_AVAILABLE",
            field_name="capacity",
        )
        current_load = _normalize_int(
            mentor.current_load,
            rule_code="CAPACITY_AVAILABLE",
            field_name="current_load",
        )
        is_active = mentor.is_active if isinstance(mentor.is_active, bool) else _normalize_bool(
            mentor.is_active,
            field_name="is_active",
        )
        mentor_type_text = _normalize_text(mentor.mentor_type).upper()
        if mentor_type_text not in {"NORMAL", "SCHOOL"}:
            raise NormalizationError(
                "SCHOOL_TYPE_COMPATIBLE",
                "نوع منتور مجاز نیست.",
                {"mentor_type": mentor.mentor_type},
            )
        special_schools = frozenset(
            _normalize_int(
                value,
                rule_code="SCHOOL_TYPE_COMPATIBLE",
                field_name="special_school",
            )
            for value in mentor.special_schools
        )
        manager_id = _normalize_int(
            mentor.manager_id,
            rule_code="MANAGER_CENTER_GATE",
            field_name="manager_id",
            allow_none=True,
        )
        return NormalizedMentor(
            mentor_id=mentor_id or 0,
            gender=gender,
            allowed_groups=allowed_groups,
            allowed_centers=allowed_centers,
            capacity=capacity or 0,
            current_load=current_load or 0,
            is_active=is_active,
            mentor_type=mentor_type_text,  # type: ignore[assignment]
            special_schools=special_schools,
            manager_id=manager_id,
        )

    def evaluate(
        self, student: StudentLike | NormalizedStudent, mentor: MentorLike | NormalizedMentor
    ) -> tuple[bool, List[TraceEntry]]:
        try:
            normalized_student = (
                student
                if isinstance(student, NormalizedStudent)
                else self.normalize_student(student)
            )
            normalized_mentor = (
                mentor
                if isinstance(mentor, NormalizedMentor)
                else self.normalize_mentor(mentor)
            )
        except NormalizationError as error:
            details = {"message": str(error)}
            details.update(error.details)
            trace = [
                {
                    "code": error.rule_code,
                    "passed": False,
                    "details": details,
                }
            ]
            return False, trace
        return self._run_rules(normalized_student, normalized_mentor)

    def _run_rules(
        self, student: NormalizedStudent, mentor: NormalizedMentor
    ) -> tuple[bool, List[TraceEntry]]:
        trace: List[TraceEntry] = []
        policy_passed = True
        for rule in self._rules:
            result: RuleResult
            result = rule.check(student, mentor)
            trace.append({"code": rule.code, "passed": result.passed, "details": result.details})
            if not result.passed:
                policy_passed = False
                if self.config.fast_fail:
                    break
        if not policy_passed and self.config.trace_limit_rejected is not None:
            trace = trace[: self.config.trace_limit_rejected]
        return policy_passed, trace


def prepare_student(
    policy: EligibilityPolicy, student: StudentLike
) -> NormalizedStudent:
    """Helper to normalize a student outside policy evaluate."""

    return policy.normalize_student(student)


def prepare_mentor(
    policy: EligibilityPolicy, mentor: MentorLike
) -> NormalizedMentor:
    """Helper to normalize a mentor outside policy evaluate."""

    return policy.normalize_mentor(mentor)

