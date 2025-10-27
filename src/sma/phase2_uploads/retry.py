from __future__ import annotations

from hashlib import blake2b
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
    seed: str,
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
            digest = blake2b(f"{seed}:{attempt}".encode("utf-8"), digest_size=8)
            fraction = int.from_bytes(digest.digest(), "big") / float(2**64)
            jitter = delay * fraction
            sleep(jitter)
    raise RetryError("operation failed after retries") from last_exc
