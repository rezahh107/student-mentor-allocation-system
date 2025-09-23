from __future__ import annotations

import asyncio

import pytest

from src.api.mock_data import MockBackend
from tests.fixtures.factories import make_student, make_mentor


@pytest.mark.asyncio
async def test_rule_filters_gender_center_schooltype_education_status():
    backend = MockBackend()
    # override mentors with controlled set
    backend._mentors = [
        make_mentor(1, gender=1, school=False, centers=[1], groups=["konkoori"]),
        make_mentor(2, gender=0, school=False, centers=[1], groups=["konkoori"]),
        make_mentor(3, gender=1, school=True, centers=[1], groups=["konkoori"]),
    ]

    # normal male student center 1
    s_normal = make_student(1, gender=1, center=1, school=False, level="konkoori")
    ranked = backend.rank_mentors_for_student(s_normal)
    assert [m.id for m in ranked] == [1]

    # school-based male student needs school mentor with code
    s_school = make_student(2, gender=1, center=1, school=True, level="konkoori")
    ranked2 = backend.rank_mentors_for_student(s_school)
    assert [m.id for m in ranked2] == [3]

    # wrong center should exclude mentor 1
    s_other_center = make_student(3, gender=1, center=2, school=False, level="konkoori")
    assert backend.rank_mentors_for_student(s_other_center) == []


def test_ranking_by_remaining_capacity_and_tie_break():
    backend = MockBackend()
    # three compatible mentors with different remaining capacity
    backend._mentors = [
        make_mentor(5, gender=1, capacity=60, current=59, school=False),  # rem=1
        make_mentor(3, gender=1, capacity=60, current=10, school=False),  # rem=50
        make_mentor(4, gender=1, capacity=60, current=10, school=False),  # rem=50 (tie -> lower id wins)
    ]
    s = make_student(10, gender=1, center=1, school=False)
    ranked = backend.rank_mentors_for_student(s)
    assert [m.id for m in ranked] == [3, 4, 5]


@pytest.mark.asyncio
async def test_create_allocation_honors_capacity_and_rules():
    backend = MockBackend()
    m = make_mentor(7, gender=1, capacity=1, current=0, school=False)
    backend._mentors = [m]
    s1 = make_student(100, gender=1, center=1, school=False)
    s2 = make_student(101, gender=1, center=1, school=False)
    backend._students = [s1, s2]
    alloc1 = await backend.create_allocation(s1.student_id, m.id)
    assert alloc1.status == "OK"
    with pytest.raises(Exception):
        await backend.create_allocation(s2.student_id, m.id)

