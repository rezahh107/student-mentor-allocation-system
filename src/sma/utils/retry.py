"""High-level retry helpers with deterministic jitter scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence, TypeVar

from sma.core.clock import Clock, tehran_clock
from sma.core.retry import (
    RetryExhaustedError,
    RetryMetrics,
    RetryPolicy,
    build_retry_metrics,
    build_sync_clock_sleeper,
    execute_with_retry,
)

T = TypeVar("T")


@dataclass(slots=True)
class RetryConfig:
    attempts: int
    base_ms: int
    max_ms: int
    jitter_seed: str
    op: str = "retry_operation"
    retryable: Sequence[type[Exception]] = (Exception,)

    def policy(self) -> RetryPolicy:
        return RetryPolicy(
            base_delay=self.base_ms / 1000,
            factor=2.0,
            max_delay=self.max_ms / 1000,
            max_attempts=self.attempts,
        )


def _jitter_seed(namespace: str, correlation_id: str | None) -> str:
    return f"{namespace}:{correlation_id or namespace}"


def deterministic_schedule(
    *, attempts: int, base_ms: int, max_ms: int, jitter_seed: str, op: str = "retry_operation"
) -> List[float]:
    config = RetryConfig(attempts=attempts, base_ms=base_ms, max_ms=max_ms, jitter_seed=jitter_seed, op=op)
    schedule: List[float] = []
    policy = config.policy()
    for attempt in range(1, attempts):
        backoff = policy.backoff_for(attempt, correlation_id=jitter_seed, op=op)
        schedule.append(backoff)
    return schedule


def retry(
    func: Callable[[], T],
    *,
    attempts: int,
    base_ms: int,
    max_ms: int,
    jitter_seed: str,
    clock: Clock | None = None,
    retryable: Iterable[type[Exception]] | None = None,
    op: str = "retry_operation",
    correlation_id: str | None = None,
    sleeper=None,
    metrics: RetryMetrics | None = None,
) -> T:
    config = RetryConfig(
        attempts=attempts,
        base_ms=base_ms,
        max_ms=max_ms,
        jitter_seed=jitter_seed,
        op=op,
        retryable=tuple(retryable) if retryable is not None else (Exception,),
    )
    actual_clock = clock or tehran_clock()
    sleeper_fn = sleeper or build_sync_clock_sleeper(actual_clock)
    seed = _jitter_seed(jitter_seed, correlation_id)
    try:
        return execute_with_retry(
            func,
            policy=config.policy(),
            clock=actual_clock,
            sleeper=sleeper_fn,
            retryable=config.retryable,
            correlation_id=seed,
            op=op,
            metrics=metrics,
        )
    except RetryExhaustedError as exc:
        raise RetryExhaustedError(op=op, correlation_id=seed, last_error=exc.last_error) from exc


__all__ = [
    "RetryConfig",
    "RetryExhaustedError",
    "RetryMetrics",
    "deterministic_schedule",
    "retry",
    "build_retry_metrics",
]
