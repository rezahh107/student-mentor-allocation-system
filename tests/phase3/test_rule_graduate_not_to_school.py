from __future__ import annotations

from sma.phase3_allocation.rules import GraduateNotToSchoolRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_graduate_blocked_from_school() -> None:
    student = normalized_student(edu_status=0)
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = GraduateNotToSchoolRule().check(student, mentor)
    assert result.passed is False
    assert "فارغ‌التحصیل" in result.details["message"]


def test_graduate_allowed_to_normal_mentor() -> None:
    student = normalized_student(edu_status=0)
    mentor = normalized_mentor(mentor_type="NORMAL")
    result = GraduateNotToSchoolRule().check(student, mentor)
    assert result.passed is True


def test_non_graduate_to_school_allowed_by_rule() -> None:
    student = normalized_student(edu_status=1)
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = GraduateNotToSchoolRule().check(student, mentor)
    assert result.passed is True


def test_graduate_rule_does_not_modify_details_when_passed() -> None:
    student = normalized_student(edu_status=1)
    mentor = normalized_mentor(mentor_type="NORMAL")
    result = GraduateNotToSchoolRule().check(student, mentor)
    assert result.details == {}


def test_graduate_rule_handles_high_edu_status() -> None:
    student = normalized_student(edu_status=5)
    mentor = normalized_mentor(mentor_type="NORMAL")
    result = GraduateNotToSchoolRule().check(student, mentor)
    assert result.passed is True

