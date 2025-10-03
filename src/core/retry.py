"""Deterministic retry helpers with metrics instrumentation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import wraps
from hashlib import blake2b
from typing import Any, Awaitable, Callable, Iterable, Protocol, TypeVar

from prometheus_client import Counter, Histogram, REGISTRY

from .clock import Clock

T = TypeVar("T")


class Sleeper(Protocol):
    """Protocol for synchronous sleep implementations."""

    def __call__(self, seconds: float) -> None:  # pragma: no cover - protocol
        ...


class AsyncSleeper(Protocol):
    async def __call__(self, seconds: float) -> None:  # pragma: no cover - protocol
        ...


def _safe_metric(factory, name: str, description: str, **kwargs):
    try:
        return factory(name, description, **kwargs)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


retry_attempts_total = _safe_metric(
    Counter,
    "retry_attempts_total",
    "Total retry attempts per operation and outcome.",
    labelnames=("op", "outcome"),
)

retry_exhaustion_total = _safe_metric(
    Counter,
    "retry_exhaustion_total",
    "Total number of times retries were exhausted.",
    labelnames=("op",),
)

retry_backoff_seconds = _safe_metric(
    Histogram,
    "retry_backoff_seconds",
    "Histogram for retry backoff durations in seconds.",
    labelnames=("op",),
)


@dataclass(slots=True)
class RetryPolicy:
    base_delay: float = 0.1
    factor: float = 2.0
    max_delay: float = 5.0
    max_attempts: int = 3

    def backoff_for(self, attempt: int, *, correlation_id: str, op: str) -> float:
        """Return deterministic backoff including jitter for attempt (1-indexed)."""

        attempt = max(1, attempt)
        raw = min(self.base_delay * (self.factor ** (attempt - 1)), self.max_delay)
        digest = blake2b(f"{correlation_id}:{op}:{attempt}".encode("utf-8"), digest_size=2).digest()
        jitter_seed = int.from_bytes(digest, "big") % 100
        jitter_multiplier = 1 + jitter_seed / 1000
        return raw * jitter_multiplier


class RetryExhaustedError(RuntimeError):
    def __init__(self, *, op: str, correlation_id: str, last_error: Exception) -> None:
        super().__init__(
            "RETRY_EXHAUSTED: «در حال حاضر امکان انجام عملیات نیست؛ لطفاً بعداً دوباره تلاش کنید.»"
        )
        self.op = op
        self.correlation_id = correlation_id
        self.last_error = last_error


def _should_retry(exception: Exception, retryable: Iterable[type[Exception]]) -> bool:
    return any(isinstance(exception, exc_type) for exc_type in retryable)


def _record_metrics(*, op: str, attempt: int, outcome: str, backoff: float | None) -> None:
    retry_attempts_total.labels(op=op, outcome=outcome).inc()
    if backoff is not None:
        retry_backoff_seconds.labels(op=op).observe(backoff)


def execute_with_retry(
    func: Callable[[], T],
    *,
    policy: RetryPolicy,
    clock: Clock,
    sleeper: Sleeper,
    retryable: Iterable[type[Exception]],
    correlation_id: str,
    op: str,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = func()
        except Exception as exc:  # pragma: no cover - broad catch required for retry
            last_error = exc
            if not _should_retry(exc, retryable) or attempt >= policy.max_attempts:
                _record_metrics(op=op, attempt=attempt, outcome="failure", backoff=None)
                retry_exhaustion_total.labels(op=op).inc()
                raise RetryExhaustedError(op=op, correlation_id=correlation_id, last_error=exc) from exc
            backoff = policy.backoff_for(attempt, correlation_id=correlation_id, op=op)
            _record_metrics(op=op, attempt=attempt, outcome="retry", backoff=backoff)
            sleeper(backoff)
        else:
            _record_metrics(op=op, attempt=attempt, outcome="success", backoff=None)
            return result
    assert last_error is not None  # pragma: no cover - defensive guard
    raise RetryExhaustedError(op=op, correlation_id=correlation_id, last_error=last_error)


async def execute_with_retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    clock: Clock,
    sleeper: AsyncSleeper,
    retryable: Iterable[type[Exception]],
    correlation_id: str,
    op: str,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await func()
        except Exception as exc:  # pragma: no cover - see sync version
            last_error = exc
            if not _should_retry(exc, retryable) or attempt >= policy.max_attempts:
                _record_metrics(op=op, attempt=attempt, outcome="failure", backoff=None)
                retry_exhaustion_total.labels(op=op).inc()
                raise RetryExhaustedError(op=op, correlation_id=correlation_id, last_error=exc) from exc
            backoff = policy.backoff_for(attempt, correlation_id=correlation_id, op=op)
            _record_metrics(op=op, attempt=attempt, outcome="retry", backoff=backoff)
            await sleeper(backoff)
        else:
            _record_metrics(op=op, attempt=attempt, outcome="success", backoff=None)
            return result
    assert last_error is not None  # pragma: no cover - defensive guard
    raise RetryExhaustedError(op=op, correlation_id=correlation_id, last_error=last_error)


def build_sync_clock_sleeper(clock: Clock) -> Sleeper:
    """Return a synchronous sleeper advancing deterministic clocks when possible."""

    def _sleep(seconds: float) -> None:
        tick = getattr(clock, "tick", None)
        if callable(tick):  # pragma: no branch - simple guard
            tick(seconds)  # type: ignore[misc]

    return _sleep


def build_async_clock_sleeper(clock: Clock) -> AsyncSleeper:
    """Return an async sleeper compatible with deterministic retry tests."""

    async def _sleep(seconds: float) -> None:
        tick = getattr(clock, "tick", None)
        if callable(tick):  # pragma: no branch - simple guard
            tick(seconds)  # type: ignore[misc]
        await asyncio.sleep(0)

    return _sleep


def retryable(
    *,
    policy: RetryPolicy,
    clock: Clock,
    sleeper: Sleeper,
    retryable_exceptions: Iterable[type[Exception]],
    op: str,
    correlation_id_fn: Callable[..., str],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for synchronous retry operations."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            correlation_id = correlation_id_fn(*args, **kwargs)
            return execute_with_retry(
                lambda: func(*args, **kwargs),
                policy=policy,
                clock=clock,
                sleeper=sleeper,
                retryable=retryable_exceptions,
                correlation_id=correlation_id,
                op=op,
            )

        return wrapper

    return decorator


def retryable_async(
    *,
    policy: RetryPolicy,
    clock: Clock,
    sleeper: AsyncSleeper,
    retryable_exceptions: Iterable[type[Exception]],
    op: str,
    correlation_id_fn: Callable[..., str],
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for asynchronous retry operations."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            correlation_id = correlation_id_fn(*args, **kwargs)
            return await execute_with_retry_async(
                lambda: func(*args, **kwargs),
                policy=policy,
                clock=clock,
                sleeper=sleeper,
                retryable=retryable_exceptions,
                correlation_id=correlation_id,
                op=op,
            )

        return wrapper

    return decorator


__all__ = [
    "AsyncSleeper",
    "Sleeper",
    "RetryPolicy",
    "RetryExhaustedError",
    "execute_with_retry",
    "execute_with_retry_async",
    "retryable",
    "retryable_async",
    "retry_attempts_total",
    "retry_exhaustion_total",
    "retry_backoff_seconds",
    "build_sync_clock_sleeper",
    "build_async_clock_sleeper",
]

