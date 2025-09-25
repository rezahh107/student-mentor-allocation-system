from __future__ import annotations

from src.phase3_allocation.rules import CenterAllowedRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_center_allowed_pass_default() -> None:
    student = normalized_student(reg_center=0)
    mentor = normalized_mentor(allowed_centers=frozenset({0, 1}))
    result = CenterAllowedRule().check(student, mentor)
    assert result.passed is True


def test_center_allowed_pass_other_center() -> None:
    student = normalized_student(reg_center=2)
    mentor = normalized_mentor(allowed_centers=frozenset({1, 2}))
    result = CenterAllowedRule().check(student, mentor)
    assert result.passed is True


def test_center_allowed_fail() -> None:
    student = normalized_student(reg_center=1)
    mentor = normalized_mentor(allowed_centers=frozenset({0}))
    result = CenterAllowedRule().check(student, mentor)
    assert result.passed is False


def test_center_allowed_details_contains_center() -> None:
    student = normalized_student(reg_center=1)
    mentor = normalized_mentor(allowed_centers=frozenset({0}))
    result = CenterAllowedRule().check(student, mentor)
    assert result.details["reg_center"] == 1


def test_center_allowed_message_is_persian() -> None:
    student = normalized_student(reg_center=1)
    mentor = normalized_mentor(allowed_centers=frozenset({0}))
    result = CenterAllowedRule().check(student, mentor)
    assert "مرکز" in result.details["message"]

