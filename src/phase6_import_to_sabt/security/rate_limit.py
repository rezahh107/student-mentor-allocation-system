"""Deterministic rate-limit helper tailored for ImportToSabt exports."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Dict, Tuple

from phase6_import_to_sabt.clock import Clock, ensure_clock


@dataclass(frozen=True)
class RateLimitSettings:
    """User-configurable rate-limit knobs with deterministic cloning support."""

    requests: int = 30
    window_seconds: int = 60
    penalty_seconds: int = 120

    def snapshot(self) -> "RateLimitSettings":
        return RateLimitSettings(
            requests=self.requests,
            window_seconds=self.window_seconds,
            penalty_seconds=self.penalty_seconds,
        )


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int
    remaining: int


class ExportRateLimiter:
    """Minimal in-memory limiter with deterministic hashing and cloning."""

    def __init__(
        self,
        *,
        settings: RateLimitSettings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = (settings or RateLimitSettings()).snapshot()
        self._clock = ensure_clock(clock, timezone="Asia/Tehran")
        self._counters: Dict[Tuple[str, int], int] = {}

    @property
    def settings(self) -> RateLimitSettings:
        return self._settings

    def snapshot(self) -> RateLimitSettings:
        return self._settings.snapshot()

    def restore(self, settings: RateLimitSettings) -> None:
        self.configure(settings)

    def configure(self, settings: RateLimitSettings) -> None:
        if settings.requests < 1:
            raise ValueError("requests must be positive")
        if settings.window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        if settings.penalty_seconds < 1:
            raise ValueError("penalty_seconds must be positive")
        self._settings = settings.snapshot()
        self._counters.clear()

    def check(self, identifier: str) -> RateLimitDecision:
        now = int(self._clock.now().timestamp())
        window = now // self._settings.window_seconds
        hashed = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        key = (hashed, window)
        count = self._counters.get(key, 0) + 1
        self._counters[key] = count
        self._cleanup(window)
        remaining = max(self._settings.requests - count, 0)
        if count > self._settings.requests:
            return RateLimitDecision(False, self._settings.penalty_seconds, remaining)
        return RateLimitDecision(True, 0, remaining)

    def _cleanup(self, current_window: int) -> None:
        expired = [key for key in self._counters if key[1] < current_window]
        for key in expired:
            self._counters.pop(key, None)


__all__ = ["ExportRateLimiter", "RateLimitDecision", "RateLimitSettings"]
