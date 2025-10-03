from __future__ import annotations

import asyncio
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from redis.asyncio import Redis

from phase6_import_to_sabt.app.clock import Clock


class SupportsNamespace(Protocol):
    namespace: str


class KeyValueStore(Protocol):
    async def incr(self, key: str, ttl_seconds: int) -> int:
        ...

    async def get(self, key: str) -> Optional[str]:
        ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def set_if_not_exists(self, key: str, value: str, ttl_seconds: int) -> bool:
        ...


@dataclass
class RedisKeyValueStore:
    client: Redis
    namespace: str

    async def incr(self, key: str, ttl_seconds: int) -> int:
        namespaced = self._namespaced(key)
        async with self.client.pipeline(transaction=True) as pipe:
            while True:
                try:
                    pipe.watch(namespaced)
                    current = await pipe.get(namespaced)
                    next_value = int(current or 0) + 1
                    pipe.multi()
                    pipe.set(namespaced, next_value, ex=ttl_seconds)
                    await pipe.execute()
                    return next_value
                except Exception:
                    await pipe.reset()
                    await asyncio.sleep(0)  # cooperative retry

    async def get(self, key: str) -> Optional[str]:
        result = await self.client.get(self._namespaced(key))
        return result.decode("utf-8") if isinstance(result, bytes) else result

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self.client.set(self._namespaced(key), value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self.client.delete(self._namespaced(key))

    async def set_if_not_exists(self, key: str, value: str, ttl_seconds: int) -> bool:
        result = await self.client.set(self._namespaced(key), value, ex=ttl_seconds, nx=True)
        return bool(result)

    def _namespaced(self, key: str) -> str:
        return f"{self.namespace}:{key}"


class InMemoryKeyValueStore:
    def __init__(self, namespace: str, clock: Clock) -> None:
        self.namespace = namespace
        self._clock = clock
        self._store: Dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()

    async def incr(self, key: str, ttl_seconds: int) -> int:
        async with self._lock:
            self._expire_locked()
            expiry, stored_value = self._store.get(key, (0.0, "0"))
            next_value = int(stored_value) + 1
            self._store[key] = (self._clock.now().timestamp() + ttl_seconds, str(next_value))
            return next_value

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            self._expire_locked()
            data = self._store.get(key)
            return data[1] if data else None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._store[key] = (self._clock.now().timestamp() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def set_if_not_exists(self, key: str, value: str, ttl_seconds: int) -> bool:
        async with self._lock:
            self._expire_locked()
            if key in self._store:
                return False
            self._store[key] = (self._clock.now().timestamp() + ttl_seconds, value)
            return True

    def _expire_locked(self) -> None:
        now_ts = self._clock.now().timestamp()
        expired = [k for k, (exp, _) in self._store.items() if exp <= now_ts]
        for key in expired:
            self._store.pop(key, None)


def encode_response(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def decode_response(raw: str) -> Dict[str, Any]:
    return json.loads(raw)


__all__ = [
    "KeyValueStore",
    "RedisKeyValueStore",
    "InMemoryKeyValueStore",
    "encode_response",
    "decode_response",
]
