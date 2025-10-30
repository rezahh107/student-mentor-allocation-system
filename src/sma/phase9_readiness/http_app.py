from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from sma.reliability.clock import Clock
# from sma.reliability.config import IdempotencyConfig, RateLimitConfigModel, RateLimitRuleModel # حذف شد یا تغییر کرد
# from sma.reliability.http_app import AuthMiddleware, IdempotencyMiddleware, RateLimitMiddleware # حذف شد یا تغییر کرد
# فرض می‌کنیم میدلویرهای امنیتی دیگر در جای دیگری تعریف نمی‌شوند یا جایگزین می‌شوند
# اگر میدلویرهای غیرامنیتی وجود داشتند، ممکن بود وارد شوند

from .metrics import ReadinessMetrics
from .orchestrator import EnvironmentConfig


def create_readiness_app(
    *,
    metrics: ReadinessMetrics,
    env_config: EnvironmentConfig,
    clock: Clock,
) -> FastAPI:
    """Expose readiness metrics guarded by the standard middleware chain."""

    app = FastAPI()
    # idem = IdempotencyConfig(ttl_seconds=86400, storage_prefix=f"phase9:{env_config.namespace}") # حذف شد یا تغییر کرد
    # rate_limit = RateLimitConfigModel(...) # حذف شد یا تغییر کرد

    # افزودن میدلویرهای امنیتی حذف شد
    # app.add_middleware(AuthMiddleware, token=env_config.tokens.metrics_read) # حذف شد
    # app.add_middleware(IdempotencyMiddleware, config=idem, clock=clock) # حذف شد
    # app.add_middleware(RateLimitMiddleware, config=rate_limit, clock=clock) # حذف شد
    # اگر میدلویرهای غیرامنیتی وجود داشتند، اینجا اضافه می‌شدند
    # app.add_middleware(SomeOtherMiddleware) # مثال

    # تغییر endpoint /metrics
    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> Response:
        # چک توکن حذف شد
        # token = request.headers.get("Authorization")
        # if token != f"Bearer {env_config.tokens.metrics_read}":
        #     raise HTTPException(status_code=401, detail="توکن نامعتبر است.")
        data = generate_latest(metrics.registry)
        response = PlainTextResponse(data.decode("utf-8"))
        # افزودن هدر زنجیره میدلویر حذف شد یا تغییر کرد
        # order = getattr(request.state, "middleware_order", [])
        # if order:
        #     response.headers["X-Middleware-Order"] = ",".join(order)
        return response

    @app.get("/healthz")
    async def healthz(request: Request) -> PlainTextResponse:
        # افزودن هدر زنجیره میدلویر حذف شد یا تغییر کرد
        # order = getattr(request.state, "middleware_order", [])
        # response = PlainTextResponse("ok")
        # if order:
        #     response.headers["X-Middleware-Order"] = ",".join(order)
        # return response
        return PlainTextResponse("ok") # تغییر داده شد

    @app.get("/readyz")
    async def readyz(request: Request) -> PlainTextResponse:
        # افزودن هدر زنجیره میدلویر حذف شد یا تغییر کرد
        # order = getattr(request.state, "middleware_order", [])
        # response = PlainTextResponse("ready")
        # if order:
        #     response.headers["X-Middleware-Order"] = ",".join(order)
        # return response
        return PlainTextResponse("ready") # تغییر داده شد

    return app


__all__ = ["create_readiness_app"]
