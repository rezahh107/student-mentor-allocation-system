"""Deterministic retry helpers with BLAKE2 jitter."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from hashlib import blake2b
from typing import TypeVar

T = TypeVar("T")


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    base_delay: float,
    rid: str,
    retry_exceptions: tuple[type[Exception], ...],
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except retry_exceptions as exc:  # type: ignore[misc]
            last_error = exc
            if attempt == attempts:
                raise
            delay = _compute_delay(base_delay, attempt, rid)
            await asyncio.sleep(delay)
    assert last_error is not None  # pragma: no cover - defensive
    raise last_error


def _compute_delay(base: float, attempt: int, rid: str) -> float:
    jitter_seed = blake2b(f"{rid}:{attempt}".encode("utf-8"), digest_size=8).digest()
    jitter_fraction = int.from_bytes(jitter_seed, "big") / float(1 << 64)
    return base * (2 ** (attempt - 1)) + jitter_fraction * base


__all__ = ["retry_async"]
