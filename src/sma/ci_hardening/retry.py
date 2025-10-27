"""Deterministic retry helpers with seeded jitter."""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import blake2b
from typing import Iterable, Iterator


@dataclass(frozen=True)
class RetryConfig:
    """Configuration for exponential backoff with deterministic jitter.

    Attributes:
        max_attempts: Maximum number of retry attempts.
        base_delay: Base delay applied to the first attempt in seconds.
        jitter_ratio: Multiplier controlling deterministic jitter scaling.
    """

    max_attempts: int = 3
    base_delay: float = 0.1
    jitter_ratio: float = 0.25


def _deterministic_jitter(seed: str, attempt: int) -> float:
    """Return deterministic jitter in the range ``[0, 1)``.

    Args:
        seed: Deterministic seed string for hashing.
        attempt: Current attempt number starting at one.

    Returns:
        Floating point value within ``[0, 1)`` derived from the seed.
    """

    digest = blake2b(f"{seed}:{attempt}".encode("utf-8"), digest_size=4).digest()
    value = int.from_bytes(digest, "big") / float(2**32)
    return value


def backoff_durations(seed: str, config: RetryConfig) -> Iterator[float]:
    """Yield backoff durations for each attempt.

    Args:
        seed: Seed string used for deterministic jitter.
        config: Retry configuration specifying base delay and attempts.

    Yields:
        Floating point delay in seconds for each retry attempt.
    """

    for attempt in range(1, config.max_attempts + 1):
        base = config.base_delay * math.pow(2.0, attempt - 1)
        jitter = _deterministic_jitter(seed, attempt)
        yield base + (config.jitter_ratio * jitter)


__all__ = ["RetryConfig", "backoff_durations"]
