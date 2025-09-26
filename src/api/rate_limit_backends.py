"""Pluggable rate limiting backends supporting shared state."""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Awaitable, Callable, Protocol, cast

LOGGER = logging.getLogger(__name__)

if os.getenv("TEST_REDIS_STUB") == "1":  # pragma: no cover - test hook
    redis_asyncio = import_module("src.api.redis_stub").async_client  # type: ignore[attr-defined]
else:  # pragma: no cover - optional dependency
    try:
        import redis.asyncio as redis_asyncio  # type: ignore[no-redef]
    except Exception:  # pragma: no cover - graceful fallback when extra not installed
        redis_asyncio = None


def redis_key(namespace: str, *parts: str) -> str:
    """Build a Redis key using the common namespace layout."""

    if not namespace:
        raise ValueError("namespace must not be empty")
    cleaned = [str(part) for part in parts if str(part)]
    if not cleaned:
        raise ValueError("at least one key segment is required")
    prefix, *rest = cleaned
    segments = [prefix, namespace]
    segments.extend(rest)
    return ":".join(segments)


@dataclass(slots=True)
class RateLimitDecision:
    """Outcome of a rate-limit consumption attempt."""

    allowed: bool
    remaining: float
    retry_after: float


class RateLimitBackend(Protocol):
    """Interface all rate limit backends must implement."""

    async def consume(
        self,
        key: str,
        *,
        capacity: int,
        refill_rate_per_sec: float,
    ) -> RateLimitDecision:  # pragma: no cover - interface only
        ...


class InMemoryRateLimitBackend:
    """Process-local token bucket backend."""

    def __init__(self) -> None:
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = asyncio.Lock()

    async def consume(
        self,
        key: str,
        *,
        capacity: int,
        refill_rate_per_sec: float,
    ) -> RateLimitDecision:
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _TokenBucket(capacity=float(capacity), refill_rate=float(refill_rate_per_sec))
                self._buckets[key] = bucket
            now = time.monotonic()
            bucket.refill(now)
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return RateLimitDecision(allowed=True, remaining=bucket.tokens, retry_after=0.0)
            retry_after = bucket.time_until_token()
            return RateLimitDecision(allowed=False, remaining=0.0, retry_after=retry_after)


class RedisRateLimitBackend:
    """Redis backed token bucket implementation for multi-instance deployments."""

    _SCRIPT = """
    local key = KEYS[1]
    local capacity = tonumber(ARGV[1])
    local refill_rate = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local ttl = tonumber(ARGV[4])
    local state = redis.call('HMGET', key, 'tokens', 'timestamp')
    local tokens = tonumber(state[1])
    local last = tonumber(state[2])
    if tokens == nil then
        tokens = capacity
        last = now
    else
        local delta = math.max(0, now - last)
        tokens = math.min(capacity, tokens + delta * refill_rate)
        last = now
    end
    local allowed = 0
    local remaining = tokens
    if tokens >= 1 then
        allowed = 1
        tokens = tokens - 1
        remaining = tokens
    end
    redis.call('HMSET', key, 'tokens', tokens, 'timestamp', now)
    redis.call('EXPIRE', key, ttl)
    local retry_after = 0
    if allowed == 0 then
        if refill_rate <= 0 then
            retry_after = ttl
        else
            retry_after = math.max(0, (1 - tokens) / refill_rate)
        end
    end
    return {allowed, remaining, retry_after}
    """

    def __init__(self, url: str, *, namespace: str = "alloc") -> None:
        if redis_asyncio is None:  # pragma: no cover - dependency guard
            raise RuntimeError("redis extra is required for RedisRateLimitBackend")
        self._client = redis_asyncio.from_url(url, encoding="utf-8", decode_responses=False)
        self._namespace = namespace
        script = self._client.register_script(self._SCRIPT)
        self._script: Callable[..., Awaitable[list[float]]] = cast(Callable[..., Awaitable[list[float]]], script)

    async def consume(
        self,
        key: str,
        *,
        capacity: int,
        refill_rate_per_sec: float,
    ) -> RateLimitDecision:
        attempts = 0
        delay = 0.01
        max_attempts = 3
        while True:
            now = time.monotonic()
            ttl = max(int(math.ceil(capacity / max(refill_rate_per_sec, 0.0001))), 1) * 2
            try:
                result = await self._script(
                    keys=[key],
                    args=[capacity, refill_rate_per_sec, now, ttl],
                )
                allowed, remaining, retry_after = (
                    float(result[0]),
                    float(result[1]),
                    float(result[2]),
                )
                return RateLimitDecision(
                    allowed=bool(int(allowed)),
                    remaining=remaining,
                    retry_after=retry_after,
                )
            except Exception as exc:  # pragma: no cover - transient backend failure
                attempts += 1
                LOGGER.warning(
                    "redis rate limit consume failed",
                    extra={
                        "key": key,
                        "attempt": attempts,
                        "error": str(exc),
                    },
                )
                if attempts >= max_attempts:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.1)

    async def close(self) -> None:  # pragma: no cover - graceful shutdown hook
        await self._client.aclose()


@dataclass(slots=True)
class _TokenBucket:
    capacity: float
    refill_rate: float
    tokens: float = 0.0
    updated_at: float = time.monotonic()

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.updated_at = now

    def time_until_token(self) -> float:
        if self.tokens >= 1:
            return 0.0
        if self.refill_rate <= 0:
            return 60.0
        deficit = 1 - self.tokens
        return deficit / self.refill_rate

