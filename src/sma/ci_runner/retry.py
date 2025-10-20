"""Deterministic retry utilities with exponential backoff and jitter."""

from __future__ import annotations

import os
import random
import time
from typing import Callable, Iterable, TypeVar

from .logging_utils import configure_logging

T = TypeVar("T")


class RetryError(RuntimeError):
    """Raised when retries are exhausted."""


def retry(
    func: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    jitter: float = 0.15,
    correlation_seed: str | None = None,
) -> T:
    """Execute ``func`` with deterministic exponential backoff."""

    configure_logging()
    delay = base_delay
    rng = random.Random(correlation_seed or "ci-runner-jitter")
    sleep_enabled = os.getenv("CI_DISABLE_REAL_SLEEP", "0") == "0"
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - propagate after retries
            if attempt == attempts:
                raise RetryError(str(exc)) from exc
            sleep_for = min(max_delay, delay * (1 + rng.uniform(-jitter, jitter)))
            if sleep_enabled:
                time.sleep(sleep_for)
            delay *= 2
    raise RetryError("retry attempts exhausted")


def retry_iterable(iterator_factory: Callable[[], Iterable[T]], *args: object, **kwargs: object) -> Iterable[T]:
    """Wrap an iterable-producing callable so it is retried lazily."""

    def _runner() -> Iterable[T]:
        return iterator_factory(*args, **kwargs)

    return retry(_runner)  # type: ignore[return-value]
