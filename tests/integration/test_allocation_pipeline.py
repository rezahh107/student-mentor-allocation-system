from __future__ import annotations

import asyncio

import pytest

from src.api.mock_data import MockBackend
from tests.fixtures.factories import make_student, make_mentor


@pytest.mark.asyncio
@pytest.mark.integration
async def test_allocation_pipeline_end_to_end():
    backend = MockBackend()
    # Controlled mentors
    backend._mentors = [
        make_mentor(1, gender=1, capacity=3, current=0, school=False),
        make_mentor(2, gender=1, capacity=2, current=0, school=False),
    ]
    # Students all compatible
    backend._students = [make_student(i, gender=1, center=1, school=False) for i in range(1, 6)]

    # Allocate by ranking best-fit mentor
    allocs = []
    for s in backend._students:
        ranked = backend.rank_mentors_for_student(s)
        assert ranked
        a = await backend.create_allocation(s.student_id, ranked[0].id)
        allocs.append(a)

    # Capacity should not be exceeded: mentor1 gets 3, mentor2 gets 2
    m1 = next(m for m in backend._mentors if m.id == 1)
    m2 = next(m for m in backend._mentors if m.id == 2)
    assert m1.current_load == 3 and m2.current_load == 2
    # Students updated
    assert sum(1 for s in backend._students if s.allocation_status == "OK") == 5


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_allocation_does_not_oversubscribe():
    backend = MockBackend()
    m = make_mentor(7, gender=1, capacity=5, current=0, school=False)
    backend._mentors = [m]
    backend._students = [make_student(i, gender=1, center=1, school=False) for i in range(1, 11)]

    async def alloc(sid: int):
        try:
            return await backend.create_allocation(sid, m.id)
        except Exception:
            return None

    results = await asyncio.gather(*[alloc(s.student_id) for s in backend._students])
    success = [r for r in results if r is not None]
    # No more than capacity should succeed
    assert len(success) == 5
    assert m.current_load == 5

