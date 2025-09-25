from __future__ import annotations

from src.phase3_allocation.rules import GenderMatchRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_gender_match_pass_male() -> None:
    student = normalized_student(gender=0)
    mentor = normalized_mentor(gender=0)
    result = GenderMatchRule().check(student, mentor)
    assert result.passed is True
    assert result.details == {}


def test_gender_match_pass_female() -> None:
    student = normalized_student(gender=1)
    mentor = normalized_mentor(gender=1)
    result = GenderMatchRule().check(student, mentor)
    assert result.passed is True


def test_gender_match_fail() -> None:
    student = normalized_student(gender=0)
    mentor = normalized_mentor(gender=1)
    result = GenderMatchRule().check(student, mentor)
    assert result.passed is False


def test_gender_match_failure_details_contains_values() -> None:
    student = normalized_student(gender=1)
    mentor = normalized_mentor(gender=0)
    result = GenderMatchRule().check(student, mentor)
    assert result.details["student_gender"] == 1
    assert result.details["mentor_gender"] == 0


def test_gender_match_message_is_persian() -> None:
    student = normalized_student(gender=1)
    mentor = normalized_mentor(gender=0)
    result = GenderMatchRule().check(student, mentor)
    assert "جنسیت" in result.details["message"]

