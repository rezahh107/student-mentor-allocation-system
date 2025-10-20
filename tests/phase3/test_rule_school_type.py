from __future__ import annotations

from sma.phase3_allocation.rules import SchoolTypeCompatibleRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_school_type_pass_for_special_student() -> None:
    student = normalized_student(student_type=1, school_code=101)
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = SchoolTypeCompatibleRule().check(student, mentor)
    assert result.passed is True


def test_school_type_fail_missing_school_code() -> None:
    student = normalized_student(student_type=1, school_code=None)
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = SchoolTypeCompatibleRule().check(student, mentor)
    assert result.passed is False
    assert "مدرسه" in result.details["message"]


def test_school_type_fail_wrong_school_code() -> None:
    student = normalized_student(student_type=1, school_code=999)
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = SchoolTypeCompatibleRule().check(student, mentor)
    assert result.passed is False
    assert result.details["school_code"] == 999


def test_school_type_fail_normal_student_to_school_mentor() -> None:
    student = normalized_student(student_type=0)
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = SchoolTypeCompatibleRule().check(student, mentor)
    assert result.passed is False
    assert "عادی" in result.details["message"]


def test_school_type_warnings_propagated() -> None:
    student = normalized_student(student_type=1, school_code=101, warnings=frozenset({"student_type_mismatch_roster"}))
    mentor = normalized_mentor(mentor_type="SCHOOL")
    result = SchoolTypeCompatibleRule().check(student, mentor)
    assert result.passed is True
    assert "student_type_mismatch_roster" in result.details["warnings"]

