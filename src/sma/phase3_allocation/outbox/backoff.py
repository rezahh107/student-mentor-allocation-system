"""Backoff policy helpers for outbox retries."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BackoffPolicy:
    """Exponential backoff policy with upper bound."""

    base_seconds: float = 1.0
    cap_seconds: float = 300.0
    max_retries: int = 12

    def next_delay(self, retry_count: int) -> float:
        """Return delay in seconds for the given retry count."""

        attempt = max(retry_count, 1)
        delay = self.base_seconds * (2 ** (attempt - 1))
        if delay < self.base_seconds:
            delay = self.base_seconds
        if delay > self.cap_seconds:
            delay = self.cap_seconds
        return float(delay)
