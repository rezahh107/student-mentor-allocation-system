from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol, TypeVar

from .metrics import Metrics

T = TypeVar("T")


class SleepFn(Protocol):
    async def __call__(self, delay: float) -> None:  # pragma: no cover - protocol definition
        ...


async def default_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


@dataclass
class RetryConfig:
    attempts: int = 3
    base_delay: float = 0.05
    jitter: float = 0.01
    multiplier: float = 2.0


async def retry_async(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    config: RetryConfig,
    metrics: Optional[Metrics] = None,
    sleep: SleepFn = default_sleep,
) -> T:
    if config.attempts < 1:
        raise ValueError("حداقل یک تلاش لازم است.")

    delay = config.base_delay
    last_exc: Exception | None = None
    for attempt in range(1, config.attempts + 1):
        try:
            if metrics:
                metrics.retry_attempts.inc()
            return await coro_factory()
        except Exception as exc:  # pragma: no cover - failure path asserted in tests
            last_exc = exc
            if attempt == config.attempts:
                if metrics:
                    metrics.retry_exhausted.inc()
                raise
            jitter = random.uniform(-config.jitter, config.jitter)
            await sleep(max(delay + jitter, 0.0))
            delay *= config.multiplier
    if last_exc:
        raise last_exc
    raise RuntimeError("Retry concluded without execution")
