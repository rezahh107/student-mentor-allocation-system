from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import blake2b
from typing import Callable, Protocol, TypeVar

from src.reliability.clock import Clock

from .metrics import ReadinessMetrics


T = TypeVar("T")


class WaitStrategy(Protocol):
    def __call__(self, delay_seconds: float) -> None:
        ...


@dataclass(slots=True)
class RetryPolicy:
    """Deterministic retry helper with BLAKE2 jitter."""

    max_attempts: int
    base_delay_seconds: float
    metrics: ReadinessMetrics
    clock: Clock
    namespace: str
    wait_strategy: WaitStrategy | None = None

    def _jitter(self, attempt: int, correlation_id: str, operation: str) -> float:
        seed = f"{self.namespace}|{operation}|{attempt}|{correlation_id}|{self.clock.isoformat()}".encode(
            "utf-8"
        )
        digest = blake2b(seed, digest_size=16).digest()
        fraction = int.from_bytes(digest[:8], "big") / float(1 << 64)
        return fraction * self.base_delay_seconds

    def _next_delay(self, attempt: int, correlation_id: str, operation: str) -> float:
        exponential = self.base_delay_seconds * math.pow(2, attempt - 1)
        return exponential + self._jitter(attempt, correlation_id, operation)

    def run(
        self,
        func: Callable[[], T],
        *,
        method: str,
        operation: str,
        correlation_id: str,
        fail_open_result: Callable[[Exception], T] | None = None,
    ) -> T:
        attempt_errors: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                return func()
            except Exception as exc:  # pragma: no cover - runtime branch
                self.metrics.mark_retry(operation=operation, namespace=self.namespace)
                attempt_errors.append(repr(exc))
                if attempt >= self.max_attempts:
                    self.metrics.mark_retry_exhausted(operation=operation, namespace=self.namespace)
                    if method.upper() == "GET" and fail_open_result is not None:
                        return fail_open_result(exc)
                    raise
                delay = self._next_delay(attempt, correlation_id, operation)
                if self.wait_strategy is not None:
                    self.wait_strategy(delay)
        # Should never reach here, but satisfies type checker.
        raise RuntimeError(
            f"retry loop corrupted for {operation}: attempts={self.max_attempts} errors={attempt_errors}"
        )


__all__ = ["RetryPolicy"]
