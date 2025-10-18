from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, List, Sequence, Tuple, Type, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetrySchedule:
    attempts: int
    base_delay: float
    jitter_seed: str

    def delays(self) -> List[float]:
        values: List[float] = []
        for attempt in range(self.attempts):
            delay = self.base_delay * (2**attempt)
            jitter = _deterministic_jitter(self.jitter_seed, attempt)
            values.append(delay + jitter)
        return values


def _deterministic_jitter(seed: str, attempt: int) -> float:
    payload = f"{seed}:{attempt}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=4).digest()
    value = int.from_bytes(digest, "big")
    return (value % 1000) / 100000.0


class RetryExhaustedError(RuntimeError):
    def __init__(self, attempts: int, errors: Sequence[BaseException]):
        self.attempts = attempts
        self.errors = tuple(errors)
        message = f"retry-exhausted:{attempts}"
        super().__init__(message)


def retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.05,
    jitter_seed: str = "repo-auditor-lite",
    retry_on: Tuple[Type[BaseException], ...] = (Exception,),
    after_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    schedule = RetrySchedule(attempts=attempts, base_delay=base_delay, jitter_seed=jitter_seed)
    delays = schedule.delays()
    failures: List[BaseException] = []
    for attempt, delay in enumerate(delays, start=1):
        try:
            return operation()
        except retry_on as error:  # type: ignore[misc]
            failures.append(error)
            if attempt == attempts:
                raise RetryExhaustedError(attempts, failures) from error
            if after_retry is not None:
                after_retry(attempt, error, delay)
    raise RetryExhaustedError(attempts, failures)


__all__ = ["RetrySchedule", "retry", "RetryExhaustedError"]
