from __future__ import annotations

from sma.phase3_allocation.rules import GroupAllowedRule

from tests.phase3.conftest import normalized_mentor, normalized_student


def test_group_allowed_pass_single() -> None:
    student = normalized_student(group_code="A")
    mentor = normalized_mentor(allowed_groups=frozenset({"A", "B"}))
    result = GroupAllowedRule().check(student, mentor)
    assert result.passed is True


def test_group_allowed_pass_multiple() -> None:
    student = normalized_student(group_code="B")
    mentor = normalized_mentor(allowed_groups=frozenset({"A", "B", "C"}))
    result = GroupAllowedRule().check(student, mentor)
    assert result.passed is True


def test_group_allowed_fail() -> None:
    student = normalized_student(group_code="Z")
    mentor = normalized_mentor(allowed_groups=frozenset({"A"}))
    result = GroupAllowedRule().check(student, mentor)
    assert result.passed is False


def test_group_allowed_details_contains_group() -> None:
    student = normalized_student(group_code="Z")
    mentor = normalized_mentor(allowed_groups=frozenset({"A"}))
    result = GroupAllowedRule().check(student, mentor)
    assert result.details["group_code"] == "Z"


def test_group_allowed_message_is_persian() -> None:
    student = normalized_student(group_code="Z")
    mentor = normalized_mentor(allowed_groups=frozenset({"A"}))
    result = GroupAllowedRule().check(student, mentor)
    assert "گروه" in result.details["message"]

