# -*- coding: utf-8 -*-
from __future__ import annotations

from src.domain.allocation.engine import AllocationEngine
from tests.factories import make_mentor, make_student


def test_ranking_by_occupancy_then_load_then_id():
    s = make_student("999")
    m1 = make_mentor(1, capacity=60, current_load=30)
    m2 = make_mentor(2, capacity=60, current_load=20)
    # m2 has lower occupancy -> should be picked
    eng = AllocationEngine()
    res = eng.select_best(s, [m1, m2])
    assert res.mentor_id == 2

