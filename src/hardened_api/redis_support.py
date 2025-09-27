"""Redis-backed primitives for idempotency, rate limiting, and token revocation."""
from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from redis.asyncio import Redis

from .observability import emit_redis_retry_exhausted, get_metric


try:  # pragma: no cover - import guard for optional redis errors
    from redis.exceptions import (  # type: ignore
        ConnectionError as RedisConnectionError,
        RedisError as RedisBackendError,
        TimeoutError as RedisTimeoutError,
    )
except Exception:  # pragma: no cover - fallback when redis extras missing
    RedisBackendError = RuntimeError
    RedisConnectionError = RuntimeError
    RedisTimeoutError = RuntimeError

_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    RedisBackendError,
    RedisConnectionError,
    RedisTimeoutError,
    ConnectionError,
    TimeoutError,
    OSError,
)

_T = TypeVar("_T")


class RedisLike(Protocol):
    """Typed subset of redis-py's asyncio interface used by the API."""

    async def set(self, name: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool: ...

    async def get(self, name: str) -> bytes | None: ...

    async def delete(self, name: str) -> int: ...

    async def expire(self, name: str, time: int) -> bool: ...

    async def zadd(self, name: str, mapping: dict[str, float]) -> int: ...

    async def zremrangebyscore(self, name: str, min: float, max: float) -> int: ...

    async def zcard(self, name: str) -> int: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...

    async def exists(self, name: str) -> bool: ...

    async def flushdb(self) -> None: ...


def create_redis_client(url: str) -> Redis:
    """Instantiate an asyncio Redis client from URL."""

    return Redis.from_url(url, encoding="utf-8", decode_responses=False)


@dataclass(slots=True)
class RedisNamespaces:
    base: str

    def idempotency(self, key: str) -> str:
        return f"{self.base}:idem:{key}"

    def idempotency_lock(self, key: str) -> str:
        return f"{self.base}:idem_lock:{key}"

    def rate_limit(self, consumer: str, route: str) -> str:
        return f"{self.base}:rl:{route}:{consumer}"

    def jwt_deny(self, jti: str) -> str:
        return f"{self.base}:jwt_deny:{jti}"


class RedisOperationError(RuntimeError):
    """Domain specific Redis error after retries are exhausted."""


@dataclass(slots=True)
class RedisRetryConfig:
    attempts: int = 3
    base_delay: float = 0.05
    max_delay: float = 0.5
    jitter: float = 0.05


class RedisExecutor:
    """Execute Redis operations with configurable retries and instrumentation."""

    def __init__(
        self,
        *,
        config: RedisRetryConfig,
        namespace: str,
        rng: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._namespace = namespace
        self._rng = rng or random.random
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._attempts_metric = get_metric("redis_retry_attempts_total")
        self._exhausted_metric = get_metric("redis_retry_exhausted_total")
        self._latency_metric = get_metric("redis_operation_latency_seconds")

    @property
    def namespace(self) -> str:
        return self._namespace

    async def call(
        self,
        operation: Callable[[], Awaitable[_T]],
        *,
        op_name: str,
        correlation_id: str | None = None,
    ) -> _T:
        attempts = 0
        start = self._monotonic()
        delay = self._config.base_delay
        jitter_base = self._config.jitter
        rid = correlation_id or "-"
        last_exc: Exception | None = None
        while attempts < self._config.attempts:
            attempts += 1
            try:
                result = await operation()
                self._attempts_metric.labels(op=op_name, outcome="success").inc(attempts)
                self._latency_metric.labels(op=op_name).observe(self._monotonic() - start)
                return result
            except _RETRYABLE_ERRORS as exc:  # pragma: no cover - transient failures
                last_exc = exc
                if attempts >= self._config.attempts:
                    self._attempts_metric.labels(op=op_name, outcome="error").inc(attempts)
                    self._exhausted_metric.labels(op=op_name, outcome="error").inc()
                    self._latency_metric.labels(op=op_name).observe(self._monotonic() - start)
                    emit_redis_retry_exhausted(
                        correlation_id=rid,
                        operation=op_name,
                        attempts=attempts,
                        last_error=exc.__class__.__name__,
                        namespace=self._namespace,
                    )
                    raise RedisOperationError(str(exc)) from exc
                next_delay = min(self._config.max_delay, delay) + self._rng() * jitter_base
                await self._sleep(next_delay)
                delay = min(self._config.max_delay, delay * 2)
                continue
        if last_exc is None:
            raise RedisOperationError("redis operation failed without exception")
        raise RedisOperationError(str(last_exc)) from last_exc

    async def sleep(self, seconds: float) -> None:
        await self._sleep(seconds)


class IdempotencyConflictError(ValueError):
    """Raised when the cached payload mismatches the incoming payload."""


class IdempotencyInFlight:
    """Handle used by the request handler to finalize idempotent writes."""

    def __init__(
        self,
        *,
        redis: RedisLike,
        key: str,
        namespaces: RedisNamespaces,
        ttl_seconds: int,
        body_hash: str,
        executor: RedisExecutor,
        clock: Callable[[], float],
        correlation_id: str | None,
    ) -> None:
        self._redis = redis
        self._redis_key = namespaces.idempotency(key)
        self._lock_key = namespaces.idempotency_lock(key)
        self._ttl = ttl_seconds
        self._body_hash = body_hash
        self._executor = executor
        self._clock = clock
        self._correlation_id = correlation_id or "-"

    async def commit(self, response_payload: dict[str, Any]) -> None:
        payload = {
            "status": "completed",
            "body_hash": self._body_hash,
            "response": response_payload,
            "stored_at": int(self._clock()),
        }
        data = json.dumps(payload, ensure_ascii=False)
        await self._executor.call(
            lambda: self._redis.set(self._redis_key, data, ex=self._ttl, nx=False),
            op_name="idempotency.commit",
            correlation_id=self._correlation_id,
        )
        await self._executor.call(
            lambda: self._redis.delete(self._lock_key),
            op_name="idempotency.lock.delete",
            correlation_id=self._correlation_id,
        )

    async def abort(self) -> None:
        await self._executor.call(
            lambda: self._redis.delete(self._redis_key),
            op_name="idempotency.abort.delete",
            correlation_id=self._correlation_id,
        )
        await self._executor.call(
            lambda: self._redis.delete(self._lock_key),
            op_name="idempotency.abort.lock",
            correlation_id=self._correlation_id,
        )


class RedisIdempotencyRepository:
    """Redis-backed idempotency cache with 24h TTL."""

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        ttl_seconds: int = 86400,
        executor: RedisExecutor,
        clock: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._redis = redis
        self._namespaces = namespaces
        self._ttl = ttl_seconds
        self._executor = executor
        self._clock = clock or time.time
        self._monotonic = monotonic or time.monotonic

    async def reserve(
        self,
        key: str,
        body_hash: str,
        *,
        wait_timeout: float = 5.0,
        correlation_id: str | None = None,
    ) -> tuple[IdempotencyInFlight | None, dict[str, Any] | None]:
        redis_key = self._namespaces.idempotency(key)
        lock_key = self._namespaces.idempotency_lock(key)
        existing = await self._executor.call(
            lambda: self._redis.get(redis_key),
            op_name="idempotency.get",
            correlation_id=correlation_id,
        )
        if existing:
            decoded = json.loads(existing)
            if decoded.get("body_hash") != body_hash:
                raise IdempotencyConflictError("payload mismatch")
            if decoded.get("status") == "completed":
                return None, decoded.get("response")
        acquired = await self._executor.call(
            lambda: self._redis.set(lock_key, str(self._clock()), ex=self._ttl, nx=True),
            op_name="idempotency.lock",
            correlation_id=correlation_id,
        )
        if not acquired:
            deadline = self._monotonic() + wait_timeout
            while self._monotonic() < deadline:
                cached = await self._executor.call(
                    lambda: self._redis.get(redis_key),
                    op_name="idempotency.get",
                    correlation_id=correlation_id,
                )
                if not cached:
                    await self._executor.sleep(0.05)
                    continue
                decoded = json.loads(cached)
                if decoded.get("body_hash") != body_hash:
                    raise IdempotencyConflictError("payload mismatch")
                if decoded.get("status") == "completed":
                    return None, decoded.get("response")
                await self._executor.sleep(0.05)
            raise RedisOperationError("idempotency wait timeout exceeded")
        payload = json.dumps({"status": "pending", "body_hash": body_hash, "created_at": int(self._clock())})
        await self._executor.call(
            lambda: self._redis.set(redis_key, payload, ex=self._ttl),
            op_name="idempotency.reserve",
            correlation_id=correlation_id,
        )
        return (
            IdempotencyInFlight(
                redis=self._redis,
                key=key,
                namespaces=self._namespaces,
                ttl_seconds=self._ttl,
                body_hash=body_hash,
                executor=self._executor,
                clock=self._clock,
                correlation_id=correlation_id,
            ),
            None,
        )

    async def clear(self, pattern: str | None = None) -> None:
        await self._executor.call(
            lambda: self._redis.flushdb(),
            op_name="idempotency.flush",
            correlation_id=None,
        )


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: float | None = None


class RedisSlidingWindowLimiter:
    """Redis sorted-set based sliding window limiter."""

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        fail_open: bool = False,
        executor: RedisExecutor,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._redis = redis
        self._namespaces = namespaces
        self._fail_open = fail_open
        self._executor = executor
        self._clock = clock or time.time

    async def allow(
        self,
        consumer: str,
        route: str,
        *,
        requests: int,
        window_seconds: float,
        correlation_id: str | None = None,
    ) -> RateLimitResult:
        key = self._namespaces.rate_limit(consumer, route)
        now = self._clock()
        window_start = now - window_seconds
        try:
            await self._executor.call(
                lambda: self._redis.zremrangebyscore(key, 0, window_start),
                op_name="ratelimit.trim",
                correlation_id=correlation_id,
            )
            count = await self._executor.call(
                lambda: self._redis.zcard(key),
                op_name="ratelimit.count",
                correlation_id=correlation_id,
            )
            if count >= requests:
                oldest_score = await self._executor.call(
                    lambda: self._redis.eval(
                        "local entries = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')\n"
                        "if not entries[2] then return 0 end\n"
                        "return entries[2]",
                        1,
                        key,
                    ),
                    op_name="ratelimit.oldest",
                    correlation_id=correlation_id,
                )
                retry_after = window_seconds
                if oldest_score:
                    retry_after = max(window_seconds, (float(oldest_score) + window_seconds) - now)
                return RateLimitResult(False, 0, retry_after)
            member = f"{consumer}:{now}"
            await self._executor.call(
                lambda: self._redis.zadd(key, {member: now}),
                op_name="ratelimit.record",
                correlation_id=correlation_id,
            )
            await self._executor.call(
                lambda: self._redis.expire(key, max(1, int(window_seconds * 2))),
                op_name="ratelimit.expire",
                correlation_id=correlation_id,
            )
            remaining = max(0, requests - count - 1)
            return RateLimitResult(True, remaining)
        except RedisOperationError:
            raise
        except Exception as exc:  # pragma: no cover - network failure simulation
            if self._fail_open:
                return RateLimitResult(True, requests)
            raise RedisOperationError(str(exc)) from exc


class JWTDenyList:
    """Redis-backed JWT jti deny list."""

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        ttl_seconds: int = 86400,
        executor: RedisExecutor,
    ) -> None:
        self._redis = redis
        self._namespaces = namespaces
        self._ttl = ttl_seconds
        self._executor = executor

    async def is_revoked(self, jti: str, *, correlation_id: str | None = None) -> bool:
        key = self._namespaces.jwt_deny(jti)
        exists = await self._executor.call(
            lambda: self._redis.exists(key),
            op_name="jwt.exists",
            correlation_id=correlation_id,
        )
        return bool(exists)

    async def revoke(self, jti: str, *, expires_in: int | None = None, correlation_id: str | None = None) -> None:
        key = self._namespaces.jwt_deny(jti)
        ttl = expires_in or self._ttl
        await self._executor.call(
            lambda: self._redis.set(key, "1", ex=ttl),
            op_name="jwt.revoke",
            correlation_id=correlation_id,
        )


