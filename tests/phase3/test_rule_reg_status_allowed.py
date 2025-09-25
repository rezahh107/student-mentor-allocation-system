from __future__ import annotations

from src.phase3_allocation.rules import RegistrationStatusAllowedRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_reg_status_allowed_zero() -> None:
    student = normalized_student(reg_status=0)
    mentor = normalized_mentor()
    result = RegistrationStatusAllowedRule().check(student, mentor)
    assert result.passed is True


def test_reg_status_allowed_one() -> None:
    student = normalized_student(reg_status=1)
    mentor = normalized_mentor()
    result = RegistrationStatusAllowedRule().check(student, mentor)
    assert result.passed is True


def test_reg_status_allowed_three() -> None:
    student = normalized_student(reg_status=3)
    mentor = normalized_mentor()
    result = RegistrationStatusAllowedRule().check(student, mentor)
    assert result.passed is True


def test_reg_status_invalid_two() -> None:
    student = normalized_student(reg_status=2)
    mentor = normalized_mentor()
    result = RegistrationStatusAllowedRule().check(student, mentor)
    assert result.passed is False


def test_reg_status_invalid_message_persian() -> None:
    student = normalized_student(reg_status=2)
    mentor = normalized_mentor()
    result = RegistrationStatusAllowedRule().check(student, mentor)
    assert "وضعیت" in result.details["message"]

