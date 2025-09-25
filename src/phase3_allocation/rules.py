"""Business rules for phase 3 allocation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Protocol

from .contracts import NormalizedMentor, NormalizedStudent, RuleCode
from .providers import ManagerCentersProvider


@dataclass(frozen=True)
class RuleResult:
    """Result of a rule evaluation."""

    passed: bool
    details: Dict[str, object]


class Rule(Protocol):
    """Protocol describing rule behaviour."""

    code: RuleCode

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        """Evaluate rule on normalized entities."""


@dataclass(frozen=True)
class GenderMatchRule:
    """Ensure student and mentor gender match."""

    code: RuleCode = "GENDER_MATCH"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        passed = student.gender == mentor.gender
        details: Dict[str, object] = {}
        if not passed:
            details = {
                "message": "جنسیت دانش‌آموز و منتور هم‌خوان نیست.",
                "student_gender": student.gender,
                "mentor_gender": mentor.gender,
            }
        return RuleResult(passed=passed, details=details)


@dataclass(frozen=True)
class GroupAllowedRule:
    """Check student group membership."""

    code: RuleCode = "GROUP_ALLOWED"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        group_allowed = student.group_code in mentor.allowed_groups
        details: Dict[str, object] = {}
        if not group_allowed:
            details = {
                "message": "گروه دانش‌آموز در فهرست مجاز منتور نیست.",
                "group_code": student.group_code,
            }
        return RuleResult(passed=group_allowed, details=details)


@dataclass(frozen=True)
class CenterAllowedRule:
    """Check student center is permitted by mentor."""

    code: RuleCode = "CENTER_ALLOWED"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        center_allowed = student.reg_center in mentor.allowed_centers
        details: Dict[str, object] = {}
        if not center_allowed:
            details = {
                "message": "مرکز ثبت‌نام دانش‌آموز برای این منتور مجاز نیست.",
                "reg_center": student.reg_center,
            }
        return RuleResult(passed=center_allowed, details=details)


@dataclass(frozen=True)
class RegistrationStatusAllowedRule:
    """Validate registration status."""

    code: RuleCode = "REG_STATUS_ALLOWED"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        allowed = student.reg_status in (0, 1, 3)
        details: Dict[str, object] = {}
        if not allowed:
            details = {
                "message": "وضعیت ثبت‌نام دانش‌آموز معتبر نیست.",
                "reg_status": student.reg_status,
            }
        return RuleResult(passed=allowed, details=details)


@dataclass(frozen=True)
class CapacityAvailableRule:
    """Ensure mentor has available capacity and is active."""

    code: RuleCode = "CAPACITY_AVAILABLE"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        details: Dict[str, object] = {}
        if mentor.capacity < 0 or mentor.current_load < 0:
            details = {
                "message": "ظرفیت یا بار منتور مقدار منفی دارد.",
                "capacity": mentor.capacity,
                "current_load": mentor.current_load,
            }
            return RuleResult(passed=False, details=details)
        if not mentor.is_active:
            details = {"message": "منتور فعال نیست."}
            return RuleResult(passed=False, details=details)
        if mentor.current_load >= mentor.capacity:
            details = {
                "message": "ظرفیت منتور تکمیل شده است.",
                "capacity": mentor.capacity,
                "current_load": mentor.current_load,
            }
            return RuleResult(passed=False, details=details)
        return RuleResult(passed=True, details=details)


@dataclass(frozen=True)
class SchoolTypeCompatibleRule:
    """Ensure mentor type matches student school requirements."""

    code: RuleCode = "SCHOOL_TYPE_COMPATIBLE"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        details: Dict[str, object] = {}
        if student.warnings:
            details["warnings"] = sorted(student.warnings)
        if student.student_type == 1:
            if mentor.mentor_type != "SCHOOL":
                details.update({
                    "message": "دانش‌آموز ویژه فقط باید به منتور مدارس تخصیص یابد.",
                    "mentor_type": mentor.mentor_type,
                })
                return RuleResult(passed=False, details=details)
            if student.school_code is None:
                details.update({
                    "message": "کد مدرسه برای دانش‌آموز ویژه موجود نیست.",
                })
                return RuleResult(passed=False, details=details)
            if student.school_code not in mentor.special_schools:
                details.update({
                    "message": "مدرسه دانش‌آموز در مدارس مجاز منتور نیست.",
                    "school_code": student.school_code,
                })
                return RuleResult(passed=False, details=details)
        else:
            if mentor.mentor_type == "SCHOOL":
                details.update({
                    "message": "دانش‌آموز عادی نباید به منتور مدارس تخصیص یابد.",
                })
                return RuleResult(passed=False, details=details)
        return RuleResult(passed=True, details=details)


@dataclass(frozen=True)
class GraduateNotToSchoolRule:
    """Block graduates from being assigned to school mentors."""

    code: RuleCode = "GRADUATE_NOT_TO_SCHOOL"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        if student.edu_status == 0 and mentor.mentor_type == "SCHOOL":
            return RuleResult(
                passed=False,
                details={
                    "message": "فارغ‌التحصیل نباید به منتور مدارس تخصیص یابد.",
                },
            )
        return RuleResult(passed=True, details={})


@dataclass(frozen=True)
class ManagerCenterGateRule:
    """Validate mentor manager gate access."""

    manager_provider: ManagerCentersProvider
    code: RuleCode = "MANAGER_CENTER_GATE"

    def check(self, student: NormalizedStudent, mentor: NormalizedMentor) -> RuleResult:
        manager_id = mentor.manager_id
        if manager_id is None:
            return RuleResult(passed=True, details={})
        centers = self.manager_provider.get_allowed_centers(manager_id)
        if centers is None:
            return RuleResult(
                passed=False,
                details={
                    "message": "دسترسی مراکز برای مدیر یافت نشد.",
                    "reason": "manager_centers_not_found",
                },
            )
        if student.reg_center not in centers:
            return RuleResult(
                passed=False,
                details={
                    "message": "مرکز ثبت‌نام دانش‌آموز در سطح مدیر مجاز نیست.",
                    "reg_center": student.reg_center,
                },
            )
        return RuleResult(passed=True, details={})


ALL_RULES = (
    GenderMatchRule(),
    GroupAllowedRule(),
    CenterAllowedRule(),
    RegistrationStatusAllowedRule(),
    CapacityAvailableRule(),
    SchoolTypeCompatibleRule(),
    GraduateNotToSchoolRule(),
)
"""Rules that do not require external dependencies."""

