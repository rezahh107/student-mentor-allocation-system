from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Tuple, Type

from sma.phase6_import_to_sabt.clock import Clock, ensure_clock
from sma.phase6_import_to_sabt.metrics import ExporterMetrics

RetryableExc = Tuple[Type[BaseException], ...]


@dataclass
class RetrySchedule:
    delays: Tuple[float, ...]
    attempts: int


class RetryingExportRunner:
    """Execute export operations with deterministic exponential backoff."""

    def __init__(
        self,
        *,
        retryable: RetryableExc,
        clock: Clock,
        sleeper: Callable[[float], None],
        metrics: ExporterMetrics | None = None,
        base_delay: float = 0.1,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._retryable = retryable
        self._clock = ensure_clock(clock, timezone="Asia/Tehran")
        self._sleep = sleeper
        self._metrics = metrics
        self._base_delay = base_delay
        self._max_attempts = max_attempts

    def execute(
        self,
        func: Callable[[], object],
        *,
        reason: str,
        correlation_id: str,
    ) -> object:
        attempt = 0
        while True:
            try:
                return func()
            except self._retryable as exc:
                attempt += 1
                reason_label = f"{reason}:{type(exc).__name__}"
                if self._metrics:
                    self._metrics.record_retry_attempt(reason=reason_label)
                if attempt >= self._max_attempts:
                    if self._metrics:
                        self._metrics.record_retry_exhausted(reason=reason_label)
                    raise
                delay = self._compute_delay(attempt, correlation_id)
                self._sleep(delay)
            except Exception:
                raise

    def build_schedule(self, *, correlation_id: str) -> RetrySchedule:
        delays = tuple(self._compute_delay(attempt, correlation_id) for attempt in range(1, self._max_attempts))
        return RetrySchedule(delays=delays, attempts=self._max_attempts)

    def _compute_delay(self, attempt: int, correlation_id: str) -> float:
        digest = hashlib.blake2b(f"{correlation_id}:{attempt}".encode("utf-8"), digest_size=8).digest()
        jitter = int.from_bytes(digest, "big") / 2**64
        factor = 1 + (jitter * 0.1)
        return self._base_delay * (2 ** (attempt - 1)) * factor


__all__ = ["RetryingExportRunner", "RetrySchedule"]
