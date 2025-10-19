from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict

from src.fakeredis import FakeStrictRedis

from .clock import Clock
from .retry import RetryPolicy


@dataclass(slots=True)
class IdempotencyEnforcer:
    redis: FakeStrictRedis
    namespace: str
    clock: Clock
    retry: RetryPolicy
    ttl_seconds: int = 24 * 60 * 60

    def acquire(self, key: str, payload: Dict[str, Any]) -> bool:
        namespaced_key = f"{self.namespace}:{key}"
        payload = {"ts": self.clock.now().isoformat(), "payload": payload}

        def attempt() -> bool:
            stored = self.redis.set(namespaced_key, json.dumps(payload), ex=self.ttl_seconds, nx=True)
            return bool(stored)

        return self.retry.run(
            operation="idempotency",
            func=attempt,
            on_retry=lambda attempt, delay: None,
            on_exhausted=lambda: None,
        )

    def release(self, key: str) -> None:
        self.redis.delete(f"{self.namespace}:{key}")

    @staticmethod
    def new_namespace() -> str:
        return uuid.uuid4().hex
