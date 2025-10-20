# -*- coding: utf-8 -*-
from __future__ import annotations

from sma.core.clock import Clock, ensure_clock

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - optional
    redis = None  # type: ignore

WINDOW = 60


class RateLimiter:
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        limit: int = 100,
        *,
        clock: Clock | None = None,
    ):
        if redis is None:
            raise RuntimeError("redis-py not installed in this environment")
        self.r = redis.Redis.from_url(redis_url, decode_responses=True)
        self.limit = limit
        self._clock = ensure_clock(clock, default=Clock.for_tehran())

    def allow(self, key: str) -> bool:
        now = int(self._clock.unix_timestamp())
        k = f"ratelimit:{key}:{now // WINDOW}"
        cnt = self.r.incr(k)
        if cnt == 1:
            self.r.expire(k, WINDOW)
        return cnt <= self.limit

