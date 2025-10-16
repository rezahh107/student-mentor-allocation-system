"""Deterministic clock utilities for readiness tooling."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class DeterministicClock:
    """Deterministic clock that never touches the operating system wall clock."""

    _TZ = ZoneInfo("Asia/Tehran")

    def __init__(self, seed: str) -> None:
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self._rng = random.Random(digest)
        self._step = 0
        self._base = datetime(2024, 1, 1, 0, 0, tzinfo=self._TZ)

    def advance(self, minutes: int = 1) -> datetime:
        """Advance the synthetic clock by ``minutes`` and return the instant."""

        self._step += max(1, minutes)
        return self._base + timedelta(minutes=self._step)

    def iso(self) -> str:
        """Return an ISO-8601 timestamp in Asia/Tehran."""

        return self.advance().isoformat()

    def jitter_seconds(self, low: float = 0.05, high: float = 0.35) -> float:
        """Return deterministic jitter within bounds for retry backoff."""

        span = max(high - low, 0.01)
        return round(low + self._rng.random() * span, 6)

    def sample_duration_ms(self) -> int:
        """Return a synthetic deterministic duration sample in milliseconds."""

        base = 120 + int(self._rng.random() * 80)
        return base + self._step


__all__ = ["DeterministicClock"]
