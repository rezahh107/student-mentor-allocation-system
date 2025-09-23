# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Callable

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - optional
    redis = None  # type: ignore

WINDOW = 60


class RateLimiter:
    def __init__(self, redis_url: str = "redis://localhost:6379/0", limit: int = 100):
        if redis is None:
            raise RuntimeError("redis-py not installed in this environment")
        self.r = redis.Redis.from_url(redis_url, decode_responses=True)
        self.limit = limit

    def allow(self, key: str) -> bool:
        now = int(time.time())
        k = f"ratelimit:{key}:{now // WINDOW}"
        cnt = self.r.incr(k)
        if cnt == 1:
            self.r.expire(k, WINDOW)
        return cnt <= self.limit

