"""IO utilities for deterministic, atomic file operations."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from hashlib import blake2b
from pathlib import Path
from typing import Callable, Iterable

from core.clock import Clock as CoreClock
from core.retry import RetryPolicy
from core.retry import build_sync_clock_sleeper

from phase6_import_to_sabt.obs.metrics import ServiceMetrics

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (OSError, )


def _default_clock() -> CoreClock:
    return CoreClock.for_tehran()


def _default_sleeper(clock: CoreClock) -> Callable[[float], None]:
    base = build_sync_clock_sleeper(clock)

    def _sleep(seconds: float) -> None:
        base(seconds)
        time.sleep(seconds)

    return _sleep


def _hash_identifier(path: Path) -> str:
    digest = blake2b(str(path).encode("utf-8"), digest_size=6)
    return digest.hexdigest()


def write_atomic(
    path: Path,
    data: bytes,
    *,
    attempts: int = 3,
    base_delay: float = 0.01,
    on_retry: Callable[[int], None] | None = None,
    sleeper: Callable[[float], None] | None = None,
    metrics: ServiceMetrics | None = None,
    retry_policy: RetryPolicy | None = None,
    correlation_id: str | None = None,
    operation: str = "fs.write",
    route: str = "storage",
    retryable: Iterable[type[Exception]] = _RETRYABLE_EXCEPTIONS,
    clock: CoreClock | None = None,
) -> None:
    """Write ``data`` to ``path`` atomically within its directory."""

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f".{path.name}.tmp"
    retryable = tuple(retryable)
    policy = retry_policy or RetryPolicy(base_delay=base_delay, max_attempts=attempts)
    clock = clock or _default_clock()
    sleep = sleeper or _default_sleeper(clock)
    correlation = correlation_id or _hash_identifier(path)
    last_error: Exception | None = None
    route_label = route or "storage"

    for attempt in range(1, policy.max_attempts + 1):
        metrics_attempt = metrics.retry_attempts_total.labels(operation=operation, route=route_label) if metrics else None
        if metrics_attempt is not None:
            metrics_attempt.inc()
        fd, temp_name = tempfile.mkstemp(prefix=prefix, suffix=".part", dir=str(directory))
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return
        except tuple(retryable) as exc:  # pragma: no branch - controlled by retryable
            last_error = exc
            if on_retry is not None:
                on_retry(attempt)
            try:
                temp_path.unlink(missing_ok=True)
            except TypeError:
                if temp_path.exists():
                    temp_path.unlink()
            if attempt >= policy.max_attempts:
                if metrics is not None:
                    metrics.retry_exhausted_total.labels(operation=operation, route=route_label).inc()
                logger.error(
                    "fs.write.retry_exhausted",
                    extra={
                        "correlation_id": correlation,
                        "op": operation,
                        "route": route_label,
                        "attempt": attempt,
                        "last_error": str(exc),
                    },
                )
                raise
            backoff = policy.backoff_for(attempt, correlation_id=correlation, op=operation)
            if metrics is not None:
                metrics.retry_backoff_seconds.labels(operation=operation, route=route_label).observe(backoff)
            sleep(backoff)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except TypeError:
                if temp_path.exists():
                    temp_path.unlink()
            raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except TypeError:
                if temp_path.exists():
                    temp_path.unlink()
    if last_error is not None:  # pragma: no cover - defensive
        raise last_error


__all__ = ["write_atomic"]

