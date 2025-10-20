from __future__ import annotations

import random

import pytest

from sma.api.mock_data import MockBackend
from tests.fixtures.factories import make_mentor, make_student


@pytest.mark.performance
def test_rank_mentors_scaling_benchmark(benchmark):
    backend = MockBackend()
    # 50 mentors mixed, all compatible with male students
    backend._mentors = [
        make_mentor(i, gender=1, capacity=random.randint(40, 80), current=random.randint(0, 30), school=False)
        for i in range(1, 51)
    ]
    students = [make_student(i, gender=1, center=1, school=False) for i in range(1, 10_001)]

    def run():
        # Rank first 10000 students; ensure function is performant
        for s in students:
            backend.rank_mentors_for_student(s)

    benchmark(run)

