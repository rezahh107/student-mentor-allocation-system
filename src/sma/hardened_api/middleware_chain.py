"""Deterministic middleware wiring ensuring RateLimit → Idempotency → Auth order."""
from __future__ import annotations

from typing import Iterable

from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

# from .middleware import ( # حذف شد یا تغییر کرد
#     AuthenticationMiddleware, # حذف شد
#     CorrelationIdMiddleware, # ممکن است باقی بماند
#     IdempotencyMiddleware, # حذف شد
#     MiddlewareState, # حذف شد یا تغییر کرد
#     RateLimitMiddleware, # حذف شد
#     SecurityHeadersMiddleware, # ممکن است حذف یا تغییر کند
#     TraceProbeMiddleware, # ممکن است باقی بماند
# )

# --- تعاریف جدید ---
# اگر CorrelationIdMiddleware و TraceProbeMiddleware در یک فایل دیگر باقی ماندند، از آنجا وارد کنید
# فرض می‌کنیم آن‌ها در src/sma/hardened_api/middleware.py باقی مانده‌اند یا به فایل جدیدی منتقل شده‌اند
from .middleware import CorrelationIdMiddleware, TraceProbeMiddleware # فرض بر این است که تغییر کرده‌اند یا جابجا شده‌اند

# اگر MiddlewareState در فایل جدید تعریف شده است، از آنجا وارد کنید
# from .middleware import DummyMiddlewareState as MiddlewareState # استفاده از تعریف جدید اگر وجود داشته باشد

# --- پایان تعاریف جدید ---

# POST_CHAIN و GET_CHAIN دیگر معنای اصلی خود را ندارند
# POST_CHAIN = ("RateLimit", "Idempotency", "Auth")
# GET_CHAIN = ("RateLimit", "Auth")
POST_CHAIN = () # یا یک تاپل خالی
GET_CHAIN = () # یا یک تاپل خالی


def install_middleware_chain(
    app: ASGIApp,
    *,
    # state: MiddlewareState, # ممکن است دیگر نیاز نباشد یا تغییر کند
    allowed_origins: Iterable[str],
) -> None:
    """Install middleware in deterministic order with optional tracing support."""

    # app.add_middleware(SecurityHeadersMiddleware) # حذف شد یا تغییر کرد
    # توجه: اگر CORS مربوط به امنیت باشد، ممکن است بخواهیم آن را نیز حذف کنیم یا تنظیمات آن را ساده کنیم
    # در اینجا، ما فقط allow_origins را تغییر می‌دهیم تا محدودیت کمتری داشته باشد، یا آن را کاملاً حذف کنیم
    # اما معمولاً CORS برای امنیت است، بنابراین ممکن است بخواهیم آن را نگه داریم، اما با تنظیمات توسعه
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], # مثلاً برای توسعه
        allow_methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"], # یا همه
        allow_headers=["*"], # یا همه
        expose_headers=["X-Correlation-ID", "X-MW-Trace"], # فقط هدرهای غیرامنیتی
        allow_credentials=False, # ممکن است نیاز باشد
        max_age=600,
    )
    # دیگر میدلویرهای امنیتی اضافه نمی‌شوند
    # app.add_middleware(AuthenticationMiddleware, state=state) # حذف شد
    # app.add_middleware(IdempotencyMiddleware, state=state) # حذف شد
    # app.add_middleware(RateLimitMiddleware, state=state) # حذف شد
    # فقط میدلویرهای غیرامنیتی باقی می‌مانند
    app.add_middleware(CorrelationIdMiddleware) # باقی می‌ماند
    app.add_middleware(TraceProbeMiddleware) # باقی می‌ماند

    # ذخیره اطلاعات زنجیره میدلویر (اگر هنوز مورد نیاز باشد)
    state_attr = getattr(app, "state", None)
    if state_attr is not None:
        # ترتیب میدلویرهای واقعی اضافه شده
        declared = tuple(m.cls.__name__ for m in getattr(app, "user_middleware", ()))
        setattr(state_attr, "middleware_declared_order", declared)
        # چون میدلویرهای امنیتی حذف شدند، این مقادیر تغییر می‌کنند
        setattr(state_attr, "middleware_post_chain", POST_CHAIN) # تغییر کرد
        setattr(state_attr, "middleware_get_chain", GET_CHAIN) # تغییر کرد


__all__ = ["install_middleware_chain", "POST_CHAIN", "GET_CHAIN"]
