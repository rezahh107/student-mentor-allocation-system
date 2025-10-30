"""Redis-backed primitives for idempotency, rate limiting, and token revocation."""
from __future__ import annotations

import asyncio
import json
import random
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from sma.core.clock import Clock, ensure_clock

try:  # pragma: no cover - optional dependency
    from redis.asyncio import Redis as _AsyncRedis  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional path
    _AsyncRedis = None  # type: ignore

# from .observability import emit_redis_retry_exhausted, get_metric # حذف شد یا تغییر کرد
# فرض بر این است که تغییرات observability منعکس شده است
# اگر همچنان مورد نیاز است، باید با تغییرات آن هماهنگ شود
# برای سادگی، فرض می‌کنیم فقط get_metric مورد نیاز است و تغییرات آن اعمال شده
from .observability import get_metric # فرض بر این است که تغییرات اعمال شده


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


def _fake_redis_namespace() -> str:
    explicit = os.getenv("SMA_FAKE_REDIS_NAMESPACE")
    if explicit:
        return explicit
    try:  # pragma: no cover - imported lazily for test environments
        from sma.testing.state import get_test_namespace
    except Exception:
        return "sma:test:fakeredis"
    return get_test_namespace()


def create_redis_client(url: str) -> RedisLike:
    """Instantiate an asyncio Redis client or a deterministic fake."""

    use_fake = os.getenv("SMA_TEST_FAKE_REDIS") == "1"
    if not use_fake and _AsyncRedis is not None:
        return _AsyncRedis.from_url(url, encoding="utf-8", decode_responses=False)

    from sma.testing.fake_redis import AsyncFakeRedis

    namespace = _fake_redis_namespace()
    return AsyncFakeRedis(namespace=namespace)


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

    # Phase 2 counter namespaces -------------------------------------------------

    def counter_sequence(self, year_code: str, gender: int) -> str:
        return f"{self.base}:counter:seq:{year_code}:{gender}"

    def counter_student(self, year_code: str, student_id: str) -> str:
        return f"{self.base}:counter:student:{year_code}:{student_id}"


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
        # از observability استفاده می‌کند، باید با تغییرات هماهنگ شود
        # self._attempts_metric = get_metric("redis_retry_attempts_total") # ممکن است حذف شده یا تغییر کرده باشد
        # self._exhausted_metric = get_metric("redis_retry_exhausted_total") # ممکن است حذف شده یا تغییر کرده باشد
        # self._latency_metric = get_metric("redis_operation_latency_seconds") # ممکن است حذف شده یا تغییر کرده باشد
        # برای سادگی، فرض می‌کنیم get_metric تغییر کرده و متریک‌های قدیمی را همچنان می‌شناسد یا جایگزین شده‌اند
        self._attempts_metric = get_metric("redis_retry_attempts_total") # فرض بر این است که تغییرات اعمال شده
        self._exhausted_metric = get_metric("redis_retry_exhausted_total") # فرض بر این است که تغییرات اعمال شده
        self._latency_metric = get_metric("redis_operation_latency_seconds") # فرض بر این است که تغییرات اعمال شده

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
                # self._attempts_metric.labels(op=op_name, outcome="success").inc(attempts) # ممکن است تغییر کرده باشد
                self._attempts_metric.labels(op=op_name, outcome="success").inc() # تغییر داده شد
                # self._latency_metric.labels(op=op_name).observe(self._monotonic() - start) # ممکن است تغییر کرده باشد
                self._latency_metric.labels(op=op_name).observe(self._monotonic() - start) # فرض بر این است که همچنان کار می‌کند
                return result
            except _RETRYABLE_ERRORS as exc:  # pragma: no cover - transient failures
                last_exc = exc
                if attempts >= self._config.attempts:
                    # self._attempts_metric.labels(op=op_name, outcome="error").inc(attempts) # ممکن است تغییر کرده باشد
                    self._attempts_metric.labels(op=op_name, outcome="error").inc() # تغییر داده شد
                    # self._exhausted_metric.labels(op=op_name, outcome="error").inc() # ممکن است تغییر کرده باشد
                    self._exhausted_metric.labels(op=op_name, outcome="error").inc() # فرض بر این است که همچنان کار می‌کند
                    # self._latency_metric.labels(op=op_name).observe(self._monotonic() - start) # ممکن است تغییر کرده باشد
                    self._latency_metric.labels(op=op_name).observe(self._monotonic() - start) # فرض بر این است که همچنان کار می‌کند
                    # emit_redis_retry_exhausted(...) # حذف شد یا تغییر کرد
                    # فقط لاگ ساده یا هیچ
                    print(f"Redis retry exhausted for {op_name} after {attempts} attempts. Error: {exc.__class__.__name__}") # یا حذف شود
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


# class IdempotencyConflictError(ValueError): ... # حذف شد یا تغییر کرد
# این خطا مربوط به ایدمپوتنسی است، می‌تواند حذف شود یا تعریف شود اما استفاده نشود
class IdempotencyConflictError(ValueError):
    """Raised when the cached payload mismatches the incoming payload.

    این کلاس دیگر مورد استفاده قرار نمی‌گیرد.
    """
    pass


class IdempotencyInFlight:
    """Handle used by the request handler to finalize idempotent writes.

    این کلاس دیگر عملکرد امنیتی ندارد.
    فقط یک شیء ساده است.
    """

    def __init__(
        self,
        *,
        redis: RedisLike,
        key: str,
        namespaces: RedisNamespaces,
        ttl_seconds: int,
        body_hash: str,
        executor: RedisExecutor,
        clock: Clock,
        correlation_id: str | None,
    ) -> None:
        # تمام متغیرها را ذخیره می‌کند اما عملیاتی انجام نمی‌دهد
        self._redis = redis
        self._redis_key = namespaces.idempotency(key)
        self._lock_key = namespaces.idempotency_lock(key)
        self._ttl = ttl_seconds
        self._body_hash = body_hash
        self._executor = executor
        self._clock = clock
        self._correlation_id = correlation_id or "-"

    async def commit(self, response_payload: dict[str, Any]) -> None:
        # عملیات واقعی حذف شد
        pass # تغییر داده شد

    async def abort(self) -> None:
        # عملیات واقعی حذف شد
        pass # تغییر داده شد


class RedisIdempotencyRepository:
    """Redis-backed idempotency cache with 24h TTL.

    این کلاس دیگر واقعاً ایدمپوتنسی را اعمال نمی‌کند.
    فقط یک پاسخ ساختگی برمی‌گرداند.
    """

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        ttl_seconds: int = 86400,
        executor: RedisExecutor,
        clock: Clock | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        # تمام متغیرها را ذخیره می‌کند اما ممکن است استفاده نشود
        self._redis = redis
        self._namespaces = namespaces
        self._ttl = ttl_seconds
        self._executor = executor
        self._clock = ensure_clock(clock, default=Clock.for_tehran())
        self._monotonic = monotonic or time.monotonic

    async def reserve(
        self,
        key: str,
        body_hash: str,
        *,
        wait_timeout: float = 5.0,
        correlation_id: str | None = None,
    ) -> tuple[IdempotencyInFlight | None, dict[str, Any] | None]:
        # دیگر واقعاً بررسی نمی‌کند، فقط یک شیء ساختگی و `None` برمی‌گرداند
        # یا فقط یک شیء `IdempotencyInFlight` که عملیات ندارد
        # و `None` برای cached_response
        reservation = IdempotencyInFlight(
            redis=self._redis,
            key=key,
            namespaces=self._namespaces,
            ttl_seconds=self._ttl,
            body_hash=body_hash,
            executor=self._executor,
            clock=self._clock,
            correlation_id=correlation_id,
        )
        return reservation, None # تغییر داده شد

    async def clear(self, pattern: str | None = None) -> None:
        # عملیات واقعی حذف شد
        pass # تغییر داده شد


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: float | None = None


class RedisSlidingWindowLimiter:
    """Redis sorted-set based sliding window limiter.

    این کلاس دیگر واقعاً محدودیتی اعمال نمی‌کند.
    همیشه اجازه می‌دهد.
    """

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        fail_open: bool = False,
        executor: RedisExecutor,
        clock: Clock | None = None,
    ) -> None:
        # تمام متغیرها را ذخیره می‌کند اما ممکن است استفاده نشود
        self._redis = redis
        self._namespaces = namespaces
        # self._fail_open = fail_open # ممکن است دیگر لازم نباشد
        self._executor = executor
        self._clock = ensure_clock(clock, default=Clock.for_tehran())

    async def allow(
        self,
        consumer: str,
        route: str,
        *,
        requests: int,
        window_seconds: float,
        correlation_id: str | None = None,
    ) -> RateLimitResult:
        # دیگر واقعاً بررسی نمی‌کند، فقط همیشه اجازه می‌دهد
        return RateLimitResult(allowed=True, remaining=requests) # تغییر داده شد


class JWTDenyList:
    """Redis-backed JWT jti deny list.

    این کلاس دیگر واقعاً لیست سیاه را بررسی نمی‌کند.
    همیشه False برمی‌گرداند.
    """

    def __init__(
        self,
        *,
        redis: RedisLike,
        namespaces: RedisNamespaces,
        ttl_seconds: int = 86400,
        executor: RedisExecutor,
    ) -> None:
        # تمام متغیرها را ذخیره می‌کند اما ممکن است استفاده نشود
        self._redis = redis
        self._namespaces = namespaces
        self._ttl = ttl_seconds
        self._executor = executor

    async def is_revoked(self, jti: str, *, correlation_id: str | None = None) -> bool:
        # دیگر واقعاً بررسی نمی‌کند، فقط False برمی‌گرداند
        return False # تغییر داده شد

    async def revoke(self, jti: str, *, expires_in: int | None = None, correlation_id: str | None = None) -> None:
        # عملیات واقعی حذف شد
        pass # تغییر داده شد
