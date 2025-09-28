from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import redis


@dataclass
class RateLimitConfig:
    capacity: int = 5
    refill_rate: float = 1.0
    namespace: str = "automation_audit:ratelimit"


class RateLimiter:
    def __init__(self, client: redis.Redis, config: RateLimitConfig, clock: Callable[[], float] = time.time) -> None:
        self.client = client
        self.config = config
        self.clock = clock

    def _key(self, token: str) -> str:
        return f"{self.config.namespace}:{token}"

    def allow(self, token: str) -> bool:
        now = self.clock()
        key = self._key(token)
        bucket = self.client.hgetall(key)

        def _to_float(value):
            if value in (None, b"", ""):
                return 0.0
            if isinstance(value, bytes):
                value = value.decode()
            return float(value)

        tokens = _to_float(bucket.get(b"tokens") or bucket.get("tokens") or 0)
        last = _to_float(bucket.get(b"ts") or bucket.get("ts") or 0)
        tokens = min(self.config.capacity, tokens + (now - last) * self.config.refill_rate)
        if tokens < 1:
            return False
        tokens -= 1
        self.client.hset(key, mapping={"tokens": tokens, "ts": now})
        return True

    def clear(self) -> None:
        pattern = f"{self.config.namespace}:*"
        for key in self.client.scan_iter(pattern):
            self.client.delete(key)
