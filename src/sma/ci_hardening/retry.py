"""Deterministic retry helpers with seeded jitter."""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import blake2b
from typing import Iterable, Iterator


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for exponential backoff with deterministic jitter."""

    max_attempts: int = 3
    base_delay: float = 0.1
    jitter_ratio: float = 0.25


def _deterministic_jitter(seed: str, attempt: int) -> float:
    digest = blake2b(f"{seed}:{attempt}".encode("utf-8"), digest_size=4).digest()
    value = int.from_bytes(digest, "big") / float(2**32)
    return value


def backoff_durations(seed: str, config: RetryConfig) -> Iterator[float]:
    """Yield backoff durations for each attempt."""

    for attempt in range(1, config.max_attempts + 1):
        base = config.base_delay * math.pow(2.0, attempt - 1)
        jitter = _deterministic_jitter(seed, attempt)
        yield base + (config.jitter_ratio * jitter)


__all__ = ["RetryConfig", "backoff_durations"]
