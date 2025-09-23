# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, Type


def retry(
    *,
    exceptions: tuple[Type[BaseException], ...] = (Exception,),
    attempts: int = 5,
    backoff_initial: float = 0.1,
    backoff_factor: float = 2.0,
):
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            delay = backoff_initial
            last_exc: BaseException | None = None
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as ex:  # pragma: no cover - time-based
                    last_exc = ex
                    time.sleep(delay)
                    delay *= backoff_factor
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


class CircuitBreaker:
    def __init__(self, threshold: int = 5, window_sec: float = 30.0, half_open_after: float = 5.0):
        self.threshold = threshold
        self.window_sec = window_sec
        self.half_open_after = half_open_after
        self._state = "closed"
        self._fail_count = 0
        self._opened_at = 0.0

    def call(self, fn: Callable[..., Any], *args, **kwargs):  # pragma: no cover - time-based
        now = time.time()
        if self._state == "open" and (now - self._opened_at) < self.half_open_after:
            raise RuntimeError("Circuit open")
        try:
            res = fn(*args, **kwargs)
            self._reset()
            return res
        except Exception:
            self._fail(now)
            raise

    def _fail(self, now: float):
        self._fail_count += 1
        if self._fail_count >= self.threshold:
            self._state = "open"
            self._opened_at = now

    def _reset(self):
        self._state = "closed"
        self._fail_count = 0

