"""Deterministic rate-limit helper tailored for ImportToSabt exports."""

from __future__ import annotations

from dataclasses import dataclass
# import hashlib # دیگر مورد نیاز نیست
# from typing import Dict, Tuple # دیگر مورد نیاز نیست
# from sma.phase6_import_to_sabt.clock import Clock, ensure_clock # دیگر مورد نیاز نیست


@dataclass(frozen=True)
class RateLimitSettings:
    """User-configurable rate-limit knobs with deterministic cloning support.

    این کلاس دیگر مورد استفاده قرار نمی‌گیرد، اما برای جلوگیری از خطا در فایل‌های دیگر ممکن است نگه داشته شود.
    """

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
    """Minimal in-memory limiter with deterministic hashing and cloning.

    این کلاس دیگر محدودیتی اعمال نمی‌کند.
    همیشه اجازه می‌دهد.
    """

    def __init__(
        self,
        *,
        settings: RateLimitSettings | None = None,
        clock: Clock | None = None,
    ) -> None:
        # self._settings = (settings or RateLimitSettings()).snapshot() # دیگر مورد نیاز نیست
        # self._clock = ensure_clock(clock, timezone="Asia/Tehran") # دیگر مورد نیاز نیست
        # self._counters: Dict[Tuple[str, int], int] = {} # دیگر مورد نیاز نیست
        pass # هیچ کاری نمی‌کند

    @property
    def settings(self) -> RateLimitSettings:
        # فقط یک نمونه پیش‌فرض برمی‌گرداند
        return RateLimitSettings()

    def snapshot(self) -> RateLimitSettings:
        # فقط یک نمونه پیش‌فرض برمی‌گرداند
        return RateLimitSettings()

    def restore(self, settings: RateLimitSettings) -> None:
        # هیچ کاری نمی‌کند
        pass

    def configure(self, settings: RateLimitSettings) -> None:
        # هیچ کاری نمی‌کند
        pass

    def check(self, identifier: str) -> RateLimitDecision:
        """تابع بررسی دیگر محدودیتی اعمال نمی‌کند."""
        # همیشه اجازه می‌دهد
        return RateLimitDecision(allowed=True, retry_after=0, remaining=999999)


__all__ = ["ExportRateLimiter", "RateLimitDecision", "RateLimitSettings"]
