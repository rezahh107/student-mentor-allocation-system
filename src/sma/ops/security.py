from __future__ import annotations

from fastapi import Header, HTTPException, status

# from .config import OpsSettings # ممکن است همچنان مورد نیاز باشد اگر OpsSettings در جاهای دیگری نیز استفاده شود
# اما از آنجا که این فایل فقط یک تابع امنیتی دارد، ممکن است OpsSettings فقط برای اینجا تعریف شده باشد
# بنابراین، ما OpsSettings را همچنان وارد می‌کنیم، اما تابع امنیتی آن را نادیده می‌گیرد
from .config import OpsSettings


def require_metrics_token(settings: OpsSettings, token: str | None) -> None:
    """تابع احراز هویت دیگر عملکرد امنیتی ندارد."""
    # تمام چک‌های امنیتی حذف شد
    # if token != settings.metrics_read_token:
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="دسترسی مجاز نیست")
    # فقط یک عمل خالی یا ممکن است فقط یک لاگ ساده انجام دهد
    pass # تغییر داده شد


async def metrics_guard(
    settings: OpsSettings, # ممکن است دیگر مورد نیاز نباشد، اما برای حفظ سازگاری پارامتر باقی می‌ماند
    metrics_read_token: str | None = Header(default=None, alias="X-Metrics-Token"),
) -> None:
    """تابع وابستگی احراز هویت دیگر عملکرد امنیتی ندارد."""
    # تمام چک‌های امنیتی حذف شد
    # if token != settings.metrics_read_token: ...
    # فقط فراخوانی تابع جدید خالی
    require_metrics_token(settings, metrics_read_token) # تغییر داده شد


__all__ = ["metrics_guard", "require_metrics_token"]
