from __future__ import annotations

import time
from typing import Callable, TypeVar

from phase6_import_to_sabt.sanitization import deterministic_jitter
from phase6_import_to_sabt.xlsx.metrics import ImportExportMetrics

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
    timer: Callable[[], float] | None = None,
) -> T:
    sleeper = sleeper or time.sleep
    timer = timer or time.perf_counter
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        start = timer()
        try:
            result = operation(attempt)
            duration = max(timer() - start, 0.0)
            if metrics is not None:
                metrics.retry_duration_seconds.labels(operation=seed, format=format_label).observe(duration)
            return result
        except Exception as exc:  # noqa: PERF203 - deliberate catch for retry control flow
            last_exc = exc
            if metrics is not None:
                metrics.retry_total.labels(operation=seed, format=format_label).inc()
            if attempt == attempts:
                if metrics is not None:
                    metrics.retry_exhausted_total.labels(operation=seed, format=format_label).inc()
                    metrics.retry_duration_seconds.labels(operation=seed, format=format_label).observe(
                        max(timer() - start, 0.0)
                    )
                raise
            if on_retry is not None:
                on_retry(attempt)
            delay = deterministic_jitter(base_delay, attempt, seed)
            if metrics is not None:
                metrics.retry_duration_seconds.labels(operation=seed, format=format_label).observe(
                    max(timer() - start, 0.0)
                )
                metrics.retry_backoff_seconds.labels(operation=seed, format=format_label).observe(delay)
            sleeper(delay)
    assert last_exc is not None  # pragma: no cover - defensive
    raise last_exc


__all__ = ["retry_with_backoff"]
