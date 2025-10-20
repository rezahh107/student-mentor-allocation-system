from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.05
    jitter: float = 0.01

    def iter_delays(self) -> Iterator[float]:
        delay = self.base_delay
        for attempt in range(self.attempts):
            jitter = random.uniform(-self.jitter, self.jitter)
            yield max(0.0, delay + jitter)
            delay *= 2

    def run(self, operation: str, func: Callable[[], T], *, on_retry: Callable[[int, float], None], on_exhausted: Callable[[], None]) -> T:
        last_exc: Exception | None = None
        for attempt, delay in enumerate(self.iter_delays(), start=1):
            try:
                return func()
            except Exception as exc:  # pragma: no cover - defensive path
                last_exc = exc
                on_retry(attempt, delay)
        on_exhausted()
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("operation exhausted without exception")
