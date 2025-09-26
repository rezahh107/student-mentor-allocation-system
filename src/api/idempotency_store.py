"""Idempotency response cache backends."""
from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .rate_limit_backends import redis_key

try:  # pragma: no cover - optional dependency
    import redis.asyncio as redis_asyncio
except Exception:  # pragma: no cover - graceful fallback
    redis_asyncio = None


class IdempotencyConflictError(RuntimeError):
    """Raised when the same Idempotency-Key is reused with a different payload."""


@dataclass(slots=True)
class IdempotencyRecord:
    """Stored response metadata."""

    body_hash: str
    response: dict[str, Any]
    status_code: int
    headers: dict[str, str]
    stored_at: float

    def is_expired(self, ttl_seconds: int) -> bool:
        return (time.time() - self.stored_at) > ttl_seconds


class IdempotencyStore(Protocol):
    """Interface for idempotency response stores."""

    async def get(self, key: str, *, body_hash: str, ttl_seconds: int) -> IdempotencyRecord | None:  # pragma: no cover - interface
        ...

    async def set(self, key: str, record: IdempotencyRecord, *, ttl_seconds: int) -> None:  # pragma: no cover - interface
        ...


class InMemoryIdempotencyStore:
    """Process local in-memory idempotency store."""

    def __init__(self) -> None:
        self._entries: dict[str, IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str, *, body_hash: str, ttl_seconds: int) -> IdempotencyRecord | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.is_expired(ttl_seconds):
                self._entries.pop(key, None)
                return None
            if entry.body_hash != body_hash:
                raise IdempotencyConflictError("payload mismatch")
            return entry

    async def set(self, key: str, record: IdempotencyRecord, *, ttl_seconds: int) -> None:
        async with self._lock:
            self._entries[key] = record


class RedisIdempotencyStore:
    """Redis based idempotency store for horizontal scaling."""

    def __init__(self, url: str, *, namespace: str = "alloc") -> None:
        if redis_asyncio is None:  # pragma: no cover - dependency guard
            raise RuntimeError("redis extra is required for RedisIdempotencyStore")
        self._client = redis_asyncio.from_url(url, encoding="utf-8", decode_responses=True)
        self._namespace = namespace

    async def get(self, key: str, *, body_hash: str, ttl_seconds: int) -> IdempotencyRecord | None:
        namespaced = self._key(key)
        raw = await self._client.get(namespaced)
        if raw is None:
            return None
        payload = json.loads(raw)
        stored_hash = payload.get("body_hash")
        if stored_hash != body_hash:
            raise IdempotencyConflictError("payload mismatch")
        record = IdempotencyRecord(
            body_hash=stored_hash,
            response=payload["response"],
            status_code=int(payload["status_code"]),
            headers={k: str(v) for k, v in payload.get("headers", {}).items()},
            stored_at=float(payload.get("stored_at", time.time())),
        )
        elapsed = time.time() - record.stored_at
        if elapsed > ttl_seconds:
            await self._client.delete(namespaced)
            return None
        await self._client.expire(namespaced, max(int(math.ceil(ttl_seconds - elapsed)), 1))
        return record

    async def set(self, key: str, record: IdempotencyRecord, *, ttl_seconds: int) -> None:
        namespaced = self._key(key)
        payload = {
            "body_hash": record.body_hash,
            "response": record.response,
            "status_code": record.status_code,
            "headers": record.headers,
            "stored_at": record.stored_at,
        }
        await self._client.set(namespaced, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)

    async def close(self) -> None:  # pragma: no cover - graceful shutdown hook
        await self._client.aclose()

    def _key(self, key: str) -> str:
        return redis_key(self._namespace, "idem", key)

