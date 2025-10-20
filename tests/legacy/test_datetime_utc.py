"""تست‌های تضمین زمان UTC آگاه از منطقه."""
from __future__ import annotations

import asyncio
from datetime import UTC

from sma.api.mock_data import MockBackend
from sma.core.datetime_utils import utc_now
from tests.fixtures.factories import make_student


def test_utc_now_returns_timezone_aware() -> None:
    stamp = utc_now()
    assert stamp.tzinfo is UTC


def test_factory_student_datetimes_are_utc() -> None:
    student = make_student(5)
    assert student.created_at.tzinfo is UTC
    assert student.updated_at.tzinfo is UTC


def test_mock_backend_students_are_utc() -> None:
    backend = MockBackend()
    students = asyncio.run(backend.get_students())
    assert students
    for student in students:
        assert student.created_at.tzinfo is UTC
        assert student.updated_at.tzinfo is UTC


def test_mock_backend_allocations_are_utc() -> None:
    backend = MockBackend()
    students = asyncio.run(backend.get_students())
    assert students
    student = students[0]
    mentor = backend.rank_mentors_for_student(student)[0]
    allocation = asyncio.run(backend.create_allocation(student.student_id, mentor.id))
    assert allocation.created_at.tzinfo is UTC
