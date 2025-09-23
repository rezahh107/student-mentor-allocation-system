# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import List

import pytest

from src.domain.allocation.engine import AllocationEngine
from tests.factories import make_mentor, make_student


@pytest.mark.slow
def test_normal_load_1k_students():
    s: List = [make_student(str(i)) for i in range(1000)]
    mentors = [make_mentor(i + 1) for i in range(100)]
    eng = AllocationEngine()
    t0 = time.perf_counter()
    for st in s:
        eng.select_best(st, mentors)
    dt = time.perf_counter() - t0
    assert dt < 5.0  # rule-engine only, excludes DB

