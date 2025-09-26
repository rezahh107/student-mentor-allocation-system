"""Idempotency response cache backends."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Awaitable, Callable, Protocol
from uuid import uuid4

from .observability import Observability
from .rate_limit_backends import redis_key

if os.getenv("TEST_REDIS_STUB") == "1":  # pragma: no cover - test hook
    redis_asyncio: Any = import_module("src.api.redis_stub").async_client  # type: ignore[attr-defined]
else:  # pragma: no cover - optional dependency
    try:
        redis_asyncio = import_module("redis.asyncio")
    except Exception:  # pragma: no cover - graceful fallback
        redis_asyncio = None


LOGGER = logging.getLogger(__name__)


def _jittered_backoff(attempt: int, *, base: float, ceiling: float, salt: str) -> float:
    """Deterministic jittered exponential backoff."""
    growth = base * (2 ** max(0, attempt - 1))
    jitter_seed = hash((salt, attempt)) & 0xFFFF
    jitter = (jitter_seed % max(1, int(base * 1000))) / 1000.0
    return min(growth + jitter, ceiling)


class IdempotencyConflictError(RuntimeError):
    """Raised when the same Idempotency-Key is reused with a different payload."""


class IdempotencyDegradedError(RuntimeError):
    """Raised when the idempotency backend enters degraded mode."""


class IdempotencyLockTimeoutError(RuntimeError):
    """Raised when a distributed lock cannot be obtained within the allotted attempts."""


@dataclass(slots=True)
class IdempotencyRecord:
    """Stored response metadata."""

    body_hash: str
    payload: bytes
    status_code: int
    headers: dict[str, str]
    stored_at: float
    fencing_token: int = 0
    is_compressed: bool = False
    content_type: str = "application/json"

    def is_expired(self, ttl_seconds: int) -> bool:
        return (time.time() - self.stored_at) > ttl_seconds


@dataclass(slots=True)
class IdempotencyLock:
    """Context manager returned when an idempotency lock is acquired."""

    key: str
    token: str
    fencing_token: int
    _release_cb: Callable[[], Awaitable[None]]
    _released: bool = False

    async def __aenter__(self) -> "IdempotencyLock":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - context protocol signature
        await self.release()

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._release_cb()


class IdempotencyStore(Protocol):
    """Interface for idempotency response stores."""

    async def get(self, key: str, *, body_hash: str, ttl_seconds: int) -> IdempotencyRecord | None:
        ...

    async def set(
        self,
        key: str,
        record: IdempotencyRecord,
        *,
        ttl_seconds: int,
        fencing_token: int | None = None,
    ) -> None:
        ...

    async def acquire_lock(self, key: str, *, ttl_ms: int) -> IdempotencyLock:
        ...


class InMemoryIdempotencyStore:
    """Process local in-memory idempotency store."""

    def __init__(self) -> None:
        self._entries: dict[str, IdempotencyRecord] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()
        self._fencing_counter = 0

    async def get(self, key: str, *, body_hash: str, ttl_seconds: int) -> IdempotencyRecord | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.is_expired(ttl_seconds):
            self._entries.pop(key, None)
            return None
        if entry.body_hash != body_hash:
            raise IdempotencyConflictError("payload mismatch")
        return entry

    async def set(
        self,
        key: str,
        record: IdempotencyRecord,
        *,
        ttl_seconds: int,
        fencing_token: int | None = None,
    ) -> None:
        record.fencing_token = fencing_token or record.fencing_token
        self._entries[key] = record

    async def acquire_lock(self, key: str, *, ttl_ms: int) -> IdempotencyLock:  # noqa: ARG002 - ttl kept for parity
        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())
        await lock.acquire()
        self._fencing_counter += 1
        fencing_token = self._fencing_counter

        async def _release() -> None:
            if lock.locked():
                lock.release()

        return IdempotencyLock(key=key, token="local", fencing_token=fencing_token, _release_cb=_release)


class RedisIdempotencyStore:
    """Redis based idempotency store for horizontal scaling."""

    _LOCK_RELEASE_SCRIPT = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    end
    return 0
    """

    _LOCK_STORE_SCRIPT = """
    local record_key = KEYS[1]
    local lock_key = KEYS[2]
    local fence_key = KEYS[3]
    local payload = ARGV[1]
    local ttl = tonumber(ARGV[2])
    local token = ARGV[3]
    local fence = tonumber(ARGV[4])
    local current = redis.call('GET', lock_key)
    if current ~= token then
        return 0
    end
    redis.call('SET', record_key, payload, 'EX', ttl)
    redis.call('SET', fence_key, fence)
    return 1
    """

    def __init__(self, url: str, *, namespace: str = "alloc", observability: Observability | None = None) -> None:
        if redis_asyncio is None:  # pragma: no cover - dependency guard
            raise RuntimeError("redis extra is required for RedisIdempotencyStore")
        self._client = redis_asyncio.from_url(url, encoding="utf-8", decode_responses=True)
        self._namespace = namespace
        self._observability = observability
        self._release_script = self._client.register_script(self._LOCK_RELEASE_SCRIPT)
        self._store_script = self._client.register_script(self._LOCK_STORE_SCRIPT)

    async def get(self, key: str, *, body_hash: str, ttl_seconds: int) -> IdempotencyRecord | None:
        namespaced = self._data_key(key)
        attempts = 0
        delay = 0.01
        max_attempts = 3
        raw: str | None = None
        while True:
            try:
                raw = await self._client.get(namespaced)
                break
            except Exception as exc:  # pragma: no cover - network failure
                attempts += 1
                reason = exc.__class__.__name__
                LOGGER.warning("redis idempotency get failed", extra={"key": namespaced, "attempt": attempts, "error": str(exc)})
                if self._observability:
                    self._observability.increment_redis_retry("get", reason)
                if attempts >= max_attempts:
                    raise IdempotencyDegradedError("unable to read idempotency state") from exc
                await asyncio.sleep(_jittered_backoff(attempts, base=delay, ceiling=0.2, salt=namespaced))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("redis idempotency payload corrupt", extra={"key": namespaced})
            await self._client.delete(namespaced)
            return None
        stored_hash = payload.get("body_hash")
        if stored_hash != body_hash:
            raise IdempotencyConflictError("payload mismatch")
        payload_b64 = payload.get("payload_b64")
        if not isinstance(payload_b64, str):
            await self._client.delete(namespaced)
            return None
        try:
            payload_bytes = base64.b64decode(payload_b64.encode("ascii"))
        except (ValueError, binascii.Error):  # type: ignore[name-defined]
            await self._client.delete(namespaced)
            return None
        record = IdempotencyRecord(
            body_hash=stored_hash,
            payload=payload_bytes,
            status_code=int(payload["status_code"]),
            headers={k: str(v) for k, v in payload.get("headers", {}).items()},
            stored_at=float(payload.get("stored_at", time.time())),
            fencing_token=int(payload.get("fencing_token", 0)),
            is_compressed=bool(payload.get("compressed", False)),
            content_type=str(payload.get("content_type", "application/json")),
        )
        elapsed = time.time() - record.stored_at
        if elapsed > ttl_seconds:
            await self._client.delete(namespaced)
            return None
        await self._client.expire(namespaced, max(int(math.ceil(ttl_seconds - elapsed)), 1))
        return record

    async def set(
        self,
        key: str,
        record: IdempotencyRecord,
        *,
        ttl_seconds: int,
        fencing_token: int | None = None,
    ) -> None:
        namespaced = self._data_key(key)
        lock_key = self._lock_key(key)
        fence_key = self._fence_key(key)
        payload = {
            "body_hash": record.body_hash,
            "payload_b64": base64.b64encode(record.payload).decode("ascii"),
            "status_code": record.status_code,
            "headers": record.headers,
            "stored_at": record.stored_at,
            "fencing_token": fencing_token or record.fencing_token,
            "compressed": record.is_compressed,
            "content_type": record.content_type,
        }
        attempts = 0
        token = record.headers.get("X-Idempotency-Lock", "")
        if not token:
            token = ""
        while True:
            try:
                result = await self._store_script(
                    keys=[namespaced, lock_key, fence_key],
                    args=[json.dumps(payload, ensure_ascii=False), ttl_seconds, token, fencing_token or record.fencing_token],
                )
                if int(result or 0) == 0:
                    LOGGER.warning("idempotency lock lost before storing", extra={"key": namespaced})
                break
            except Exception as exc:  # pragma: no cover - network failure
                attempts += 1
                reason = exc.__class__.__name__
                LOGGER.warning("redis idempotency set failed", extra={"key": namespaced, "attempt": attempts, "error": str(exc)})
                if self._observability:
                    self._observability.increment_redis_retry("set", reason)
                if attempts >= 3:
                    raise IdempotencyDegradedError("unable to persist idempotency state") from exc
                await asyncio.sleep(_jittered_backoff(attempts, base=0.01, ceiling=0.2, salt=namespaced))

    async def acquire_lock(self, key: str, *, ttl_ms: int) -> IdempotencyLock:
        if ttl_ms <= 0:
            raise ValueError("ttl_ms must be positive")
        lock_key = self._lock_key(key)
        fence_key = self._fence_key(key)
        token = uuid4().hex
        for attempt in range(1, 11):
            try:
                acquired = await self._client.set(lock_key, token, nx=True, px=ttl_ms)
            except Exception as exc:  # pragma: no cover - backend failure
                reason = exc.__class__.__name__
                LOGGER.warning("redis idempotency lock acquire failed", extra={"key": lock_key, "attempt": attempt, "error": str(exc)})
                if self._observability:
                    self._observability.increment_redis_retry("lock_acquire", reason)
                if attempt >= 3:
                    raise IdempotencyDegradedError("unable to acquire idempotency lock") from exc
                await asyncio.sleep(_jittered_backoff(attempt, base=0.01, ceiling=0.2, salt=lock_key))
                continue
            if acquired:
                fencing_token = int(await self._client.incr(fence_key))
                if self._observability:
                    self._observability.increment_idempotency_lock("acquired")

                async def _release() -> None:
                    try:
                        await self._release_script(keys=[lock_key], args=[token])
                    except Exception as exc:  # pragma: no cover - release failure
                        LOGGER.warning("redis idempotency lock release failed", extra={"key": lock_key, "error": str(exc)})

                return IdempotencyLock(
                    key=key,
                    token=token,
                    fencing_token=fencing_token,
                    _release_cb=_release,
                )
            if self._observability:
                self._observability.increment_idempotency_lock_contention("busy")
            await asyncio.sleep(_jittered_backoff(attempt, base=0.01, ceiling=0.3, salt=lock_key))
        if self._observability:
            self._observability.increment_idempotency_degraded("lock-timeout")
        raise IdempotencyLockTimeoutError(f"lock acquisition timed out for {key}")

    async def close(self) -> None:  # pragma: no cover - graceful shutdown hook
        await self._client.aclose()

    def _data_key(self, key: str) -> str:
        return redis_key(self._namespace, "idem", key)

    def _lock_key(self, key: str) -> str:
        return redis_key(self._namespace, "idem-lock", key)

    def _fence_key(self, key: str) -> str:
        return redis_key(self._namespace, "idem-fence", key)
