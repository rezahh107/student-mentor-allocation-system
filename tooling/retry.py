from __future__ import annotations

"""Deterministic retry helpers with Prometheus instrumentation."""

import hashlib
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, TypeVar

from prometheus_client import Counter, Histogram

from .clock import Clock
from .metrics import (
    get_retry_counter,
    get_retry_exhaustion_counter,
    get_retry_histogram,
)

T = TypeVar("T")


class Sleeper(Protocol):
    def sleep(self, seconds: float) -> None:
        """Advance virtual time deterministically."""


@dataclass
class RetryPolicy:
    attempts: int
    base_delay: float = 0.1
    max_delay: float = 2.0

    def schedule(self, correlation_id: str, operation: str) -> Iterable[float]:
        for attempt in range(1, self.attempts + 1):
            delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
            jitter = _deterministic_jitter(correlation_id, operation, attempt)
            yield delay + jitter


def retry(
    func: Callable[[], T],
    should_retry: Callable[[BaseException], bool],
    policy: RetryPolicy,
    correlation_id: str,
    operation: str,
    clock: Sleeper | None = None,
    counter: Counter | None = None,
    histogram: Histogram | None = None,
    exhaustion_counter: Counter | None = None,
) -> T:
    """Execute ``func`` with deterministic exponential backoff."""

    sleeper: Sleeper = clock if clock is not None else Clock()
    counter = counter or get_retry_counter()
    histogram = histogram or get_retry_histogram()
    exhaustion_counter = exhaustion_counter or get_retry_exhaustion_counter()

    last_error: BaseException | None = None
    for attempt, delay in enumerate(policy.schedule(correlation_id, operation), start=1):
        try:
            result = func()
        except BaseException as exc:  # noqa: BLE001
            last_error = exc
            if should_retry(exc):
                if attempt < policy.attempts:
                    counter.labels(operation=operation, result="retry").inc()
                    histogram.labels(operation=operation).observe(delay)
                    sleeper.sleep(delay)
                    continue
                counter.labels(operation=operation, result="exhausted").inc()
                exhaustion_counter.labels(operation=operation).inc()
            else:
                counter.labels(operation=operation, result="fatal").inc()
            raise
        else:
            counter.labels(operation=operation, result="success").inc()
            return result
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry policy executed without attempts")


def _deterministic_jitter(correlation_id: str, operation: str, attempt: int) -> float:
    seed = f"{correlation_id}:{operation}:{attempt}".encode()
    digest = hashlib.blake2b(seed, digest_size=4).digest()
    value = int.from_bytes(digest, "big")
    return (value % 1000) / 10_000.0
