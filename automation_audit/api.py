from __future__ import annotations

import asyncio
from typing import Callable, Optional, Set

import redis
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.routing import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .auth import AuthConfig, AuthMiddleware
from .idem import IdempotencyStore
from .logging import log_json
from .metrics import Metrics, build_metrics, render_metrics
from .ratelimit import RateLimitConfig, RateLimiter
from .retry import RetryConfig, retry_async


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter, token_provider: Callable[[Request], str]) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.token_provider = token_provider

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - integration tested
        token = self.token_provider(request)
        if not self.limiter.allow(token):
            return JSONResponse(
                {"detail": "خطای نرخ‌دهی؛ بعداً تلاش کنید."}, status_code=status.HTTP_429_TOO_MANY_REQUESTS
            )
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, store: IdempotencyStore):
        super().__init__(app)
        self.store = store

    async def dispatch(self, request: Request, call_next):  # pragma: no cover - integration tested
        if request.method.upper() in {"POST", "PUT"}:
            key = request.headers.get("idempotency-key")
            if not key or not (8 <= len(key) <= 64):
                return JSONResponse(
                    {"detail": "کلید تکرار نامعتبر است؛ باید ۸ تا ۶۴ نویسهٔ مجاز باشد."}, status_code=status.HTTP_400_BAD_REQUEST
                )
            if not self.store.put_if_absent(key, {"method": request.method, "path": request.url.path}):
                return JSONResponse({"detail": "درخواست تکراری است."}, status_code=status.HTTP_409_CONFLICT)
        return await call_next(request)


def _extract_bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    header = header.strip()
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return None


def create_app(
    *,
    redis_client: Optional[redis.Redis] = None,
    metrics: Optional[Metrics] = None,
    auth_tokens: Optional[list[str]] = None,
    rate_limit_config: Optional[RateLimitConfig] = None,
    metrics_token: str = "metrics-token",
    metrics_allowed_ips: Optional[Set[str]] = None,
) -> FastAPI:
    redis_client = redis_client or redis.Redis(host="localhost", port=6379, decode_responses=True)
    metrics = metrics or build_metrics()
    auth_tokens = auth_tokens or ["local-token"]
    rate_limit_config = rate_limit_config or RateLimitConfig()
    allowed_metrics_ips = set(metrics_allowed_ips or set())
    combined_tokens = list({*auth_tokens, metrics_token})

    limiter = RateLimiter(redis_client, rate_limit_config)
    idem_store = IdempotencyStore(redis_client)

    app = FastAPI()

    app.add_middleware(AuthMiddleware, config=AuthConfig(combined_tokens))
    app.add_middleware(IdempotencyMiddleware, store=idem_store)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        token_provider=lambda request: request.headers.get("x-ratelimit-token", request.client.host if request.client else "anon"),
    )

    router = APIRouter()

    @router.post("/audit")
    async def run_audit(request: Request) -> dict[str, str]:
        metrics.audit_runs.inc()

        async def perform():
            await asyncio.sleep(0)
            return {"status": "ok"}

        try:
            result = await retry_async(lambda: perform(), config=RetryConfig(), metrics=metrics)
        except Exception as exc:  # pragma: no cover - error path
            metrics.audit_failures.inc()
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="خطای داخلی سامانه.") from exc
        log_json("audit_completed", status="ok")
        return result

    @router.get("/metrics")
    async def get_metrics(request: Request) -> Response:
        token = _extract_bearer_token(request.headers.get("authorization"))
        ip = _client_ip(request)
        if token != metrics_token or (allowed_metrics_ips and (ip not in allowed_metrics_ips)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="دسترسی به متریک‌ها مجاز نیست.")
        data = render_metrics(metrics)
        return Response(content=data, media_type="text/plain; version=0.0.4")

    app.include_router(router)
    return app
