from dataclasses import dataclass


@dataclass
class APIConfig:
    """پیکربندی کلاینت API.

    ویژگی‌ها:
        base_url: آدرس پایه سرویس Backend.
        timeout: حداکثر زمان انتظار هر درخواست (ثانیه).
        max_retries: حداکثر دفعات تلاش مجدد در خطاهای موقت.
        retry_delay: تاخیر پایه بین تلاش‌ها (ثانیه)؛ به‌صورت نمایی افزایش می‌یابد.
        use_mock: حالت Mock برای توسعه و تست.
        log_requests: فعال‌سازی لاگ ساخت‌یافته درخواست‌ها.
    """

    base_url: str = "http://localhost:8000"
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    use_mock: bool = True
    log_requests: bool = True

