# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from functools import wraps
from time import perf_counter
from typing import Any, Callable

log = logging.getLogger("perf")


def log_slow(threshold_ms: float = 250.0):
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                dt_ms = (perf_counter() - t0) * 1000.0
                if dt_ms >= threshold_ms:
                    log.warning("slow_op", extra={"op": fn.__name__, "duration_ms": round(dt_ms, 2)})

        return wrapper

    return decorator

