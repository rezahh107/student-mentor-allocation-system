"""Stub rate limiter that always allows requests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitSettings:
    requests: int = 30
    window_seconds: int = 60
    penalty_seconds: int = 120

    def snapshot(self) -> RateLimitSettings:
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
    """Development-friendly rate limiter that never throttles."""

    def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D401 - no-op
        return None

    @property
    def settings(self) -> RateLimitSettings:
        return RateLimitSettings()

    def snapshot(self) -> RateLimitSettings:
        return RateLimitSettings()

    def restore(self, settings: RateLimitSettings) -> None:  # pragma: no cover - noop
        return None

    def configure(self, settings: RateLimitSettings) -> None:  # pragma: no cover - noop
        return None

    def check(self, identifier: str) -> RateLimitDecision:  # noqa: D401 - always allow
        return RateLimitDecision(allowed=True, retry_after=0, remaining=999999)


__all__ = ["ExportRateLimiter", "RateLimitDecision", "RateLimitSettings"]
