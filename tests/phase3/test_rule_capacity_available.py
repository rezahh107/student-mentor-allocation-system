from __future__ import annotations

from sma.phase3_allocation.rules import CapacityAvailableRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_capacity_available_pass() -> None:
    student = normalized_student()
    mentor = normalized_mentor(capacity=5, current_load=3, is_active=True)
    result = CapacityAvailableRule().check(student, mentor)
    assert result.passed is True


def test_capacity_available_fail_inactive() -> None:
    student = normalized_student()
    mentor = normalized_mentor(is_active=False)
    result = CapacityAvailableRule().check(student, mentor)
    assert result.passed is False
    assert "فعال" in result.details["message"]


def test_capacity_available_fail_full() -> None:
    student = normalized_student()
    mentor = normalized_mentor(capacity=3, current_load=3)
    result = CapacityAvailableRule().check(student, mentor)
    assert result.passed is False
    assert result.details["capacity"] == 3


def test_capacity_available_fail_negative_capacity() -> None:
    student = normalized_student()
    mentor = normalized_mentor(capacity=-1, current_load=0)
    result = CapacityAvailableRule().check(student, mentor)
    assert result.passed is False
    assert result.details["capacity"] == -1


def test_capacity_available_fail_negative_load() -> None:
    student = normalized_student()
    mentor = normalized_mentor(capacity=5, current_load=-2)
    result = CapacityAvailableRule().check(student, mentor)
    assert result.passed is False
    assert result.details["current_load"] == -2

