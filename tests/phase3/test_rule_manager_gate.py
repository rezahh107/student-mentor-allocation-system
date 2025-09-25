from __future__ import annotations

import pytest

from src.phase3_allocation.rules import ManagerCenterGateRule

from tests.phase3.conftest import (
    DictManagerCentersProvider,
    normalized_mentor,
    normalized_student,
)


@pytest.fixture
def provider() -> DictManagerCentersProvider:
    return DictManagerCentersProvider({10: frozenset({0, 1}), 11: frozenset({2})})


def test_manager_gate_pass_without_manager(provider: DictManagerCentersProvider) -> None:
    student = normalized_student(reg_center=0)
    mentor = normalized_mentor(manager_id=None)
    result = ManagerCenterGateRule(provider).check(student, mentor)
    assert result.passed is True


def test_manager_gate_pass_with_allowed_center(provider: DictManagerCentersProvider) -> None:
    student = normalized_student(reg_center=1)
    mentor = normalized_mentor(manager_id=10)
    result = ManagerCenterGateRule(provider).check(student, mentor)
    assert result.passed is True


def test_manager_gate_fail_not_found(provider: DictManagerCentersProvider) -> None:
    student = normalized_student(reg_center=1)
    mentor = normalized_mentor(manager_id=99)
    result = ManagerCenterGateRule(provider).check(student, mentor)
    assert result.passed is False
    assert result.details["reason"] == "manager_centers_not_found"


def test_manager_gate_fail_center_not_allowed(provider: DictManagerCentersProvider) -> None:
    student = normalized_student(reg_center=0)
    mentor = normalized_mentor(manager_id=11)
    result = ManagerCenterGateRule(provider).check(student, mentor)
    assert result.passed is False
    assert result.details["reg_center"] == 0


def test_manager_gate_message_is_persian(provider: DictManagerCentersProvider) -> None:
    student = normalized_student(reg_center=0)
    mentor = normalized_mentor(manager_id=11)
    result = ManagerCenterGateRule(provider).check(student, mentor)
    assert "مرکز" in result.details["message"]

