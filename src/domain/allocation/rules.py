# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.domain.mentor.entities import Mentor
from src.domain.allocation.reasons import ReasonCode, RuleResult, build_reason
from src.domain.student.entities import Student


class Rule(Protocol):
    def check(self, student: Student, mentor: Mentor) -> RuleResult:  # pragma: no cover - simple protocol
        ...


@dataclass(slots=True)
class GenderRule:
    def check(self, student: Student, mentor: Mentor) -> RuleResult:
        if student.gender == mentor.gender:
            return RuleResult(True)
        return RuleResult(False, build_reason(ReasonCode.GENDER_MISMATCH))


@dataclass(slots=True)
class AllowedGroupRule:
    def check(self, student: Student, mentor: Mentor) -> RuleResult:
        if student.group_code in mentor.allowed_groups:
            return RuleResult(True)
        return RuleResult(False, build_reason(ReasonCode.GROUP_NOT_ALLOWED))


@dataclass(slots=True)
class AllowedCenterRule:
    def check(self, student: Student, mentor: Mentor) -> RuleResult:
        if int(student.reg_center) in mentor.allowed_centers:
            return RuleResult(True)
        return RuleResult(False, build_reason(ReasonCode.CENTER_NOT_ALLOWED))


@dataclass(slots=True)
class CapacityRule:
    def check(self, student: Student, mentor: Mentor) -> RuleResult:
        if mentor.has_capacity():
            return RuleResult(True)
        return RuleResult(False, build_reason(ReasonCode.CAPACITY_FULL))


@dataclass(slots=True)
class GraduateConstraintRule:
    def check(self, student: Student, mentor: Mentor) -> RuleResult:
        # Graduates cannot be assigned to school mentors
        if student.edu_status.value == 0 and mentor.type == "مدرسه":
            return RuleResult(False, build_reason(ReasonCode.GRADUATE_SCHOOL_FORBIDDEN))
        return RuleResult(True)


@dataclass(slots=True)
class SchoolTypeRule:
    def check(self, student: Student, mentor: Mentor) -> RuleResult:
        # School students must match school mentors with same school_code
        if student.student_type.value == 1:
            if mentor.type != "مدرسه":
                return RuleResult(False, build_reason(ReasonCode.SCHOOL_STUDENT_NEEDS_SCHOOL_MENTOR))
            if student.school_code is None or student.school_code not in mentor.school_codes:
                return RuleResult(False, build_reason(ReasonCode.SCHOOL_CODE_MISMATCH))
            return RuleResult(True)
        # Normal students cannot get school mentors (per BR-004)
        if mentor.type == "مدرسه":
            return RuleResult(False, build_reason(ReasonCode.NORMAL_STUDENT_CANNOT_GET_SCHOOL_MENTOR))
        return RuleResult(True)

