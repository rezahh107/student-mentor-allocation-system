# -*- coding: utf-8 -*-
from __future__ import annotations

from sma.core.clock import Clock, ensure_clock

# توجه: ما همچنان redis را وارد می‌کنیم، اما ممکن است استفاده نشود
# اگر کلاس‌های دیگری به این کلاس وابسته باشند، ممکن است بارگذاری شود
# اما عملکرد واقعی آن غیرفعال است
try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - optional
    redis = None  # type: ignore

WINDOW = 60 # ممکن است دیگر مورد استفاده قرار نگیرد


class RateLimiter:
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        limit: int = 100,
        *,
        clock: Clock | None = None,
    ):
        # اگرچه redis وارد شده، اما دیگر برای چیزی استفاده نمی‌شود
        # if redis is None:
        #     raise RuntimeError("redis-py not installed in this environment")
        # self.r = redis.Redis.from_url(redis_url, decode_responses=True)
        # self.limit = limit
        # self._clock = ensure_clock(clock, default=Clock.for_tehran())
        # فقط متغیرهای مورد نیاز را ذخیره می‌کنیم، اما استفاده نمی‌کنیم
        self.limit = limit
        self._clock = ensure_clock(clock, default=Clock.for_tehran())
        # یا فقط یک کلاس خالی ایجاد کنیم
        # pass

    def allow(self, key: str) -> bool:
        """تابع محدودیت دسترسی دیگر عملکرد امنیتی ندارد."""
        # عملکرد واقعی حذف شد
        # now = int(self._clock.unix_timestamp())
        # k = f"ratelimit:{key}:{now // WINDOW}"
        # cnt = self.r.incr(k)
        # if cnt == 1:
        #     self.r.expire(k, WINDOW)
        # return cnt <= self.limit
        # همیشه True برمی‌گرداند
        return True # تغییر داده شد
