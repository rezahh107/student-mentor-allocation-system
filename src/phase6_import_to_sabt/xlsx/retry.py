from __future__ import annotations

import time
from typing import Callable, TypeVar

from ..sanitization import deterministic_jitter
from .metrics import ImportExportMetrics

T = TypeVar("T")


def retry_with_backoff(
    operation: Callable[[int], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.01,
    seed: str,
    metrics: ImportExportMetrics | None,
    format_label: str,
    sleeper: Callable[[float], None] | None = None,
    on_retry: Callable[[int], None] | None = None,
) -> T:
    sleeper = sleeper or time.sleep
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation(attempt)
        except Exception as exc:  # noqa: PERF203 - deliberate catch for retry control flow
            last_exc = exc
            if metrics is not None:
                metrics.retry_total.labels(operation=seed, format=format_label).inc()
            if attempt == attempts:
                if metrics is not None:
                    metrics.retry_exhausted_total.labels(operation=seed, format=format_label).inc()
                raise
            if on_retry is not None:
                on_retry(attempt)
            delay = deterministic_jitter(base_delay, attempt, seed)
            sleeper(delay)
    assert last_exc is not None  # pragma: no cover - defensive
    raise last_exc


__all__ = ["retry_with_backoff"]
