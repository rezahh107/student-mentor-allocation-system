from __future__ import annotations

import asyncio
import secrets
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

# from .config import IdempotencyConfig, RateLimitConfigModel, ReliabilitySettings # ممکن است همچنان مورد نیاز باشد
# اگر کلاس‌های config فقط حاوی مقادیر پیکربندی باشند و خود آن‌ها امنیت نباشند، می‌توانند باقی بمانند
# اما توابع/کلاس‌هایی که با این پیکربندی‌ها کار می‌کنند (مثل میدلویرها) باید تغییر کنند
# فرض می‌کنیم این ماژول‌ها تغییر کرده‌اند یا مقادیر مربوط به امنیت در آن‌ها دیگر مورد استفاده قرار نمی‌گیرند
# from .cleanup import CleanupDaemon
# from .clock import Clock
# from .drill import DisasterRecoveryDrill
# from .logging_utils import JSONLogger
# from .metrics import ReliabilityMetrics
# این ماژول‌ها ممکن است همچنان مورد نیاز باشند، اما متد‌هایی که با امنیت سروکار دارند باید تغییر کنند

# --- تغییر توابع کمکی ---
# این توابع امنیت نیستند، بنابراین می‌توانند باقی بمانند
_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_ulid_component(value: int, length: int) -> str:
    mask = (1 << (length * 5)) - 1
    value &= mask
    chars = ["0"] * length
    for idx in range(length - 1, -1, -1):
        chars[idx] = _ULID_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


def _generate_ulid(clock) -> str: # Clock را بدون تایپ هینت بگذاریم
    timestamp_ms = int(max(0, clock.now().timestamp() * 1000))
    randomness = int.from_bytes(secrets.token_bytes(10), "big")
    return _encode_ulid_component(timestamp_ms, 10) + _encode_ulid_component(randomness, 16)


def _resolve_correlation_id(request: Request, clock) -> str: # Clock را بدون تایپ هینت بگذاریم
    header = request.headers.get("X-Request-ID")
    if header:
        candidate = header.strip()
        if candidate:
            return candidate
    return _generate_ulid(clock)
# --- پایان تغییر توابع کمکی ---


# --- تغییر میدلویر RateLimit ---
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, config, clock) -> None: # تایپ هینت‌ها را حذف کنیم یا تغییر دهیم
        super().__init__(app)
        # self.config = config # دیگر مورد نیاز نیست
        # self.clock = clock # دیگر مورد نیاز نیست
        # self._state: Dict[str, tuple[int, float]] = {} # دیگر مورد نیاز نیست
        # self._lock = asyncio.Lock() # دیگر مورد نیاز نیست

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        # تمام منطق امنیتی حذف شد
        # key = request.headers.get("X-RateLimit-Key") or "global"
        # now = self.clock.now().timestamp()
        # async with self._lock: ...
        # limit_reached = count >= self.config.default_rule.requests
        # if limit_reached and request.method != "GET" and not self.config.fail_open: ...
        # self._state[key] = (count + 1, reset_at)
        # فقط ادامه مسیر را فراخوانی می‌کند
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["RateLimit"] # می‌توان حذف یا تغییر کرد
        return await call_next(request) # تغییر داده شد


# --- تغییر میدلویر Idempotency ---
class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, config, clock) -> None: # تایپ هینت‌ها را حذف کنیم یا تغییر دهیم
        super().__init__(app)
        # self.config = config # دیگر مورد نیاز نیست
        # self.clock = clock # دیگر مورد نیاز نیست
        # self._lock = asyncio.Lock() # دیگر مورد نیاز نیست
        # self._store: Dict[str, tuple[bytes, float, Dict[str, str]]] = {} # دیگر مورد نیاز نیست

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        # فقط زنجیره میدلویر را به‌روز می‌کند (می‌توان حذف کرد)
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Idempotency"]
        # تمام منطق امنیتی/ایدمپوتنسی حذف شد
        # if request.method != "POST": ...
        # key = request.headers.get("Idempotency-Key")
        # if not key: ...
        # async with self._lock: ...
        # cached = self._store.get(key) ...
        # response = Response(content=body, headers=headers, media_type="application/json") ...
        # async for chunk in response.body_iterator: ...
        # async with self._lock: ...
        # enriched = Response(...) ...
        # فقط ادامه مسیر را فراخوانی می‌کند
        return await call_next(request) # تغییر داده شد


# --- تغییر میدلویر Auth ---
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, token: str) -> None:
        super().__init__(app)
        # self.token = token # دیگر مورد نیاز نیست

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        # فقط زنجیره میدلویر را به‌روز می‌کند (می‌توان حذف کرد)
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Auth"]
        # تمام منطق امنیتی حذف شد
        # if request.method != "GET": ...
        # header = request.headers.get("Authorization")
        # if header != f"Bearer {self.token}": ...
        # فقط ادامه مسیر را فراخوانی می‌کند
        response = await call_next(request)
        # تنظیم هدر زنجیره میدلویر (می‌توان حذف کرد)
        # order = getattr(request.state, "middleware_order", [])
        # if order: ...
        return response # تغییر داده شد


def create_reliability_app(
    *,
    settings, # ReliabilitySettings, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
    metrics, # ReliabilityMetrics, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
    retention, # RetentionEnforcer, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
    cleanup, # CleanupDaemon, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
    drill, # DisasterRecoveryDrill, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
    logger, # JSONLogger, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
    clock, # Clock, # تایپ هینت را حذف می‌کنیم یا فرض می‌کنیم تغییر کرده
) -> FastAPI:
    app = FastAPI()

    # افزودن میدلویرهای امنیتی حذف شد
    # Register in reverse so execution order becomes RateLimit -> Idempotency -> Auth
    # app.add_middleware(AuthMiddleware, token=settings.tokens.metrics_read) # حذف شد
    # app.add_middleware(IdempotencyMiddleware, config=settings.idempotency, clock=clock) # حذف شد
    # app.add_middleware(RateLimitMiddleware, config=settings.rate_limit, clock=clock) # حذف شد
    # اگر میدلویرهای غیرامنیتی وجود داشتند، اینجا اضافه می‌شدند

    @app.post("/dr/run")
    async def run_dr(request: Request) -> JSONResponse:
        correlation_id = _resolve_correlation_id(request, clock)
        # idem_key = request.headers.get("Idempotency-Key", correlation_id) # اگر میدلویر Idempotency حذف شده، این شاید دیگر کاربرد نداشته باشد
        # اما ممکن است سرویس drill هنوز نیاز داشته باشد
        # فرض کنیم drill بدون وابستگی به میدلویر کار می‌کند یا idem_key را نادیده می‌گیرد
        idem_key = request.headers.get("Idempotency-Key", correlation_id) # همچنان می‌خوانیم، اما ممکن است استفاده نشود
        report = drill.run(
            settings.artifacts_root,
            settings.backups_root / "restore",
            correlation_id=correlation_id,
            namespace=settings.redis.namespace,
            idempotency_key=idem_key,
        )
        logger.bind(correlation_id).info("dr.api.run", report=report)
        return JSONResponse(report)

    @app.post("/retention/enforce")
    async def enforce_retention(request: Request) -> JSONResponse:
        correlation_id = _resolve_correlation_id(request, clock)
        result = retention.run(enforce=True)
        logger.bind(correlation_id).info("retention.api.run", result=result)
        return JSONResponse({"correlation_id": correlation_id, **result})

    @app.post("/cleanup/run")
    async def run_cleanup(request: Request) -> JSONResponse:
        correlation_id = _resolve_correlation_id(request, clock)
        result = cleanup.run()
        payload = {
            "correlation_id": correlation_id,
            "removed_part_files": result.removed_part_files,
            "removed_links": result.removed_links,
        }
        logger.bind(correlation_id).info("cleanup.api.run", payload=payload)
        return JSONResponse(payload)

    # تغییر endpoint /metrics
    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> Response:
        # چک توکن حذف شد
        # token = request.headers.get("Authorization")
        # if token != f"Bearer {settings.tokens.metrics_read}":
        #     raise HTTPException(status_code=401, detail="توکن نامعتبر است.")
        data = generate_latest(metrics.registry)
        return PlainTextResponse(data.decode("utf-8"))

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/readyz")
    async def readyz() -> PlainTextResponse:
        return PlainTextResponse("ready")

    return app


def get_debug_context(clock=None) -> dict[str, Any]: # تایپ هینت را حذف می‌کنیم
    import os

    return {
        # "redis_keys": [], # ممکن است امنیتی باشد
        # "rate_limit_state": {}, # مربوط به میدلویر حذف شده
        # "middleware_order": [], # مربوط به میدلویرهای حذف شده
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": clock.now().isoformat() if clock else None,
        "security_removed": True, # فیلد نشان‌دهنده تغییر
    }


__all__ = ["create_reliability_app", "RateLimitMiddleware", "IdempotencyMiddleware", "AuthMiddleware", "get_debug_context"]
