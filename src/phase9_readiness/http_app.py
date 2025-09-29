from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest

from src.reliability.clock import Clock
from src.reliability.config import IdempotencyConfig, RateLimitConfigModel, RateLimitRuleModel
from src.reliability.http_app import AuthMiddleware, IdempotencyMiddleware, RateLimitMiddleware

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
    idem = IdempotencyConfig(ttl_seconds=86400, storage_prefix=f"phase9:{env_config.namespace}")
    rate_limit = RateLimitConfigModel(
        default_rule=RateLimitRuleModel(requests=120, window_seconds=60.0),
        fail_open=False,
    )

    app.add_middleware(AuthMiddleware, token=env_config.tokens.metrics_read)
    app.add_middleware(IdempotencyMiddleware, config=idem, clock=clock)
    app.add_middleware(RateLimitMiddleware, config=rate_limit, clock=clock)

    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> Response:
        token = request.headers.get("Authorization")
        if token != f"Bearer {env_config.tokens.metrics_read}":
            raise HTTPException(status_code=401, detail="توکن نامعتبر است.")
        data = generate_latest(metrics.registry)
        response = PlainTextResponse(data.decode("utf-8"))
        order = getattr(request.state, "middleware_order", [])
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        return response

    @app.get("/healthz")
    async def healthz(request: Request) -> PlainTextResponse:
        order = getattr(request.state, "middleware_order", [])
        response = PlainTextResponse("ok")
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        return response

    @app.get("/readyz")
    async def readyz(request: Request) -> PlainTextResponse:
        order = getattr(request.state, "middleware_order", [])
        response = PlainTextResponse("ready")
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        return response

    return app


__all__ = ["create_readiness_app"]
