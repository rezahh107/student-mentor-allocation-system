"""Tests for the core allocation business logic."""
from __future__ import annotations

import pytest

from sma.core.allocation_engine import AllocationEngine
from sma.core.allocation_rules import AllocationRules
from sma.core.models import Mentor, Student


def test_allocation_basic() -> None:
    student = Student(id=1, gender=1, grade_level=10, center_id=1)
    mentor = Mentor(
        id=1,
        gender=1,
        supported_grades=[10, 11],
        max_capacity=5,
        current_students=2,
        center_id=1,
        primary_grade=10,
    )

    engine = AllocationEngine()
    result = engine.allocate_students([student], [mentor])

    assert result["successful"] == 1
    assert result["failed"] == 0
    assert result["assignments"] == [
        {"student_id": 1, "mentor_id": 1, "priority_score": 180}
    ]
    assert mentor.current_students == 3


def test_allocation_gender_mismatch() -> None:
    student = Student(id=1, gender=0, grade_level=10, center_id=1)
    mentor = Mentor(
        id=1,
        gender=1,
        supported_grades=[10],
        max_capacity=2,
        current_students=0,
        center_id=1,
    )

    engine = AllocationEngine()
    result = engine.allocate_students([student], [mentor])

    assert result["successful"] == 0
    assert result["failed"] == 1
    assert result["errors"][0]["reason"] == "no mentor with matching gender"


def test_allocation_grade_mismatch() -> None:
    student = Student(id=4, gender=1, grade_level=9, center_id=1)
    mentor = Mentor(
        id=9,
        gender=1,
        supported_grades=[10, 11],
        max_capacity=3,
        current_students=1,
        center_id=1,
    )

    engine = AllocationEngine()
    result = engine.allocate_students([student], [mentor])

    assert result["failed"] == 1
    assert result["errors"][0]["reason"] == "grade level not supported"


def test_allocation_capacity_limit() -> None:
    student = Student(id=2, gender=1, grade_level=10, center_id=1)
    mentor = Mentor(
        id=2,
        gender=1,
        supported_grades=[10],
        max_capacity=1,
        current_students=1,
        center_id=1,
    )

    engine = AllocationEngine()
    result = engine.allocate_students([student], [mentor])

    assert result["failed"] == 1
    assert result["errors"][0]["reason"] == "no capacity available"


def test_priority_prefers_specialised_and_local_mentor() -> None:
    student = Student(id=5, gender=1, grade_level=10, center_id=1)
    mentor_high_priority = Mentor(
        id=100,
        gender=1,
        supported_grades=[10],
        max_capacity=5,
        current_students=4,
        center_id=1,
        primary_grade=10,
    )
    mentor_lower_priority = Mentor(
        id=200,
        gender=1,
        supported_grades=[10, 11, 12],
        max_capacity=6,
        current_students=2,
        center_id=2,
        primary_grade=11,
    )

    engine = AllocationEngine()
    result = engine.allocate_students(
        [student], [mentor_high_priority, mentor_lower_priority]
    )

    assert result["successful"] == 1
    # Expect the mentor with higher calculated priority (id=100).
    assert result["assignments"][0]["mentor_id"] == 100


def test_rules_can_assign_and_priority_alignment() -> None:
    rules = AllocationRules()
    student = Student(id=10, gender=1, grade_level=11, center_id=3)
    mentor = Mentor(
        id=10,
        gender=1,
        supported_grades=[11, 12],
        max_capacity=4,
        current_students=0,
        center_id=3,
        primary_grade=11,
    )

    assert rules.can_assign(student, mentor)
    assert rules.calculate_priority(student, mentor) == 190


def test_failure_reason_when_no_mentors() -> None:
    student = Student(id=7, gender=1, grade_level=10, center_id=1)
    engine = AllocationEngine()

    result = engine.allocate_students([student], [])

    assert result["failed"] == 1
    assert result["errors"][0]["reason"] == "no mentors available"
