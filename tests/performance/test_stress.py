# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import List

import pytest

from src.domain.allocation.engine import AllocationEngine
from tests.factories import make_mentor, make_student


@pytest.mark.stress
def test_stress_50k_students():
    n = 50000
    s: List = [make_student(str(i)) for i in range(n)]
    mentors = [make_mentor(i + 1) for i in range(1000)]
    eng = AllocationEngine()
    t0 = time.perf_counter()
    for st in s:
        eng.select_best(st, mentors)
    dt = time.perf_counter() - t0
    # Not asserting; used for measuring in CI perf job
    print({"students": n, "elapsed": dt})

