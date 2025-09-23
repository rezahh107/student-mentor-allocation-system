# -*- coding: utf-8 -*-
from __future__ import annotations

import concurrent.futures as cf
import time
from typing import List

import pytest

from src.domain.allocation.engine import AllocationEngine
from tests.factories import make_mentor, make_student


@pytest.mark.concurrent
def test_concurrent_users():
    users = 50
    per_user = 200
    mentors = [make_mentor(i + 1) for i in range(200)]

    def work(uid: int) -> int:
        eng = AllocationEngine()
        count = 0
        for i in range(per_user):
            st = make_student(f"{uid}-{i}")
            eng.select_best(st, mentors)
            count += 1
        return count

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=users) as ex:
        futs = [ex.submit(work, u) for u in range(users)]
        done = sum(f.result() for f in futs)
    dt = time.perf_counter() - t0
    assert done == users * per_user
    print({"users": users, "ops": done, "elapsed": dt})

