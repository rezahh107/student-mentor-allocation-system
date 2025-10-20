from __future__ import annotations

import random
from typing import Callable, TypeVar

T = TypeVar("T")


class RetryError(RuntimeError):
    pass


def retry(
    func: Callable[[], T],
    attempts: int,
    *,
    base_delay: float,
    max_delay: float,
    sleep: Callable[[float], None] | None = None,
    fatal_exceptions: tuple[type[BaseException], ...] = (),
) -> T:
    if attempts <= 0:
        raise ValueError("attempts must be positive")
    sleep = sleep or (lambda delay: None)
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - generic guard
            if isinstance(exc, fatal_exceptions):
                raise
            last_exc = exc
            if attempt == attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            jitter = random.uniform(0, delay)
            sleep(jitter)
    raise RetryError("operation failed after retries") from last_exc
