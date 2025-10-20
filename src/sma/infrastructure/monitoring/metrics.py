# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import wraps
from time import perf_counter
from typing import Any, Callable

from prometheus_client import Counter, Gauge, Histogram


allocation_duration_seconds = Histogram(
    "allocation_duration_seconds", "Time to allocate one student", buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2)
)
allocation_success_total = Counter("allocation_success_total", "Successful allocations")
allocation_failed_total = Counter("allocation_failed_total", "Failed allocations", ["reason"])
mentor_capacity_utilization = Gauge("mentor_capacity_utilization", "Mentor utilization", ["mentor_id"])
db_query_duration_seconds = Histogram(
    "db_query_duration_seconds", "DB query duration", buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5)
)


def record_allocation(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args, **kwargs):
        t0 = perf_counter()
        try:
            result = func(*args, **kwargs)
            allocation_success_total.inc()
            return result
        except Exception as ex:  # pragma: no cover - simplified
            allocation_failed_total.labels(reason=type(ex).__name__).inc()
            raise
        finally:
            allocation_duration_seconds.observe(perf_counter() - t0)

    return wrapper

