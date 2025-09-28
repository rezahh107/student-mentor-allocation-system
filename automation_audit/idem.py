from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import redis

IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24


@dataclass
class IdempotencyStore:
    client: redis.Redis
    namespace: str = "automation_audit:idemp"

    def _key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{self.namespace}:{digest}"

    def put_if_absent(self, key: str, payload: Any) -> bool:
        redis_key = self._key(key)
        if not self.client.set(redis_key, json.dumps(payload), nx=True, ex=IDEMPOTENCY_TTL_SECONDS):
            return False
        return True

    def get(self, key: str) -> Any | None:
        redis_key = self._key(key)
        value = self.client.get(redis_key)
        if not value:
            return None
        return json.loads(value)

    def clear_namespace(self) -> None:
        pattern = f"{self.namespace}:*"
        for key in self.client.scan_iter(pattern):
            self.client.delete(key)
