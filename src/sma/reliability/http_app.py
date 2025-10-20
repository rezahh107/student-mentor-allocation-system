from __future__ import annotations

import asyncio
import secrets
from typing import Any, Callable, Dict

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from .cleanup import CleanupDaemon
from .clock import Clock
from .config import IdempotencyConfig, RateLimitConfigModel, ReliabilitySettings
from .drill import DisasterRecoveryDrill
from .logging_utils import JSONLogger
from .metrics import ReliabilityMetrics
from .retention import RetentionEnforcer


_ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_ulid_component(value: int, length: int) -> str:
    mask = (1 << (length * 5)) - 1
    value &= mask
    chars = ["0"] * length
    for idx in range(length - 1, -1, -1):
        chars[idx] = _ULID_ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(chars)


def _generate_ulid(clock: Clock) -> str:
    timestamp_ms = int(max(0, clock.now().timestamp() * 1000))
    randomness = int.from_bytes(secrets.token_bytes(10), "big")
    return _encode_ulid_component(timestamp_ms, 10) + _encode_ulid_component(randomness, 16)


def _resolve_correlation_id(request: Request, clock: Clock) -> str:
    header = request.headers.get("X-Request-ID")
    if header:
        candidate = header.strip()
        if candidate:
            return candidate
    return _generate_ulid(clock)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, config: RateLimitConfigModel, clock: Clock) -> None:
        super().__init__(app)
        self.config = config
        self.clock = clock
        self._state: Dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        key = request.headers.get("X-RateLimit-Key") or "global"
        now = self.clock.now().timestamp()
        async with self._lock:
            count, reset_at = self._state.get(key, (0, now + self.config.default_rule.window_seconds))
            if now >= reset_at:
                count = 0
                reset_at = now + self.config.default_rule.window_seconds
            limit_reached = count >= self.config.default_rule.requests
            if limit_reached and request.method != "GET" and not self.config.fail_open:
                raise HTTPException(status_code=429, detail="نرخ درخواست مجاز نیست.")
            self._state[key] = (count + 1, reset_at)
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["RateLimit"]
        return await call_next(request)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, config: IdempotencyConfig, clock: Clock) -> None:
        super().__init__(app)
        self.config = config
        self.clock = clock
        self._lock = asyncio.Lock()
        self._store: Dict[str, tuple[bytes, float, Dict[str, str]]] = {}

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Idempotency"]
        if request.method != "POST":
            return await call_next(request)
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="کلید تکرار الزامی است.")
        now = self.clock.now().timestamp()
        async with self._lock:
            cached = self._store.get(key)
            if cached and cached[1] + self.config.ttl_seconds > now:
                body, _, headers = cached
                response = Response(content=body, headers=headers, media_type="application/json")
                order = getattr(request.state, "middleware_order", [])
                if order:
                    response.headers["X-Middleware-Order"] = ",".join(order)
                return response
        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        headers = dict(response.headers)
        async with self._lock:
            self._store[key] = (body, now, headers)
        enriched = Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
        order = getattr(request.state, "middleware_order", [])
        if order:
            enriched.headers["X-Middleware-Order"] = ",".join(order)
        return enriched


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        request.state.middleware_order = getattr(request.state, "middleware_order", []) + ["Auth"]
        if request.method != "GET":
            header = request.headers.get("Authorization")
            if header != f"Bearer {self.token}":
                raise HTTPException(status_code=401, detail="دسترسی مجاز نیست.")
        response = await call_next(request)
        order = getattr(request.state, "middleware_order", [])
        if order:
            response.headers["X-Middleware-Order"] = ",".join(order)
        return response


def create_reliability_app(
    *,
    settings: ReliabilitySettings,
    metrics: ReliabilityMetrics,
    retention: RetentionEnforcer,
    cleanup: CleanupDaemon,
    drill: DisasterRecoveryDrill,
    logger: JSONLogger,
    clock: Clock,
) -> FastAPI:
    app = FastAPI()

    # Register in reverse so execution order becomes RateLimit -> Idempotency -> Auth
    app.add_middleware(AuthMiddleware, token=settings.tokens.metrics_read)
    app.add_middleware(IdempotencyMiddleware, config=settings.idempotency, clock=clock)
    app.add_middleware(RateLimitMiddleware, config=settings.rate_limit, clock=clock)

    @app.post("/dr/run")
    async def run_dr(request: Request) -> JSONResponse:
        correlation_id = _resolve_correlation_id(request, clock)
        idem_key = request.headers.get("Idempotency-Key", correlation_id)
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

    @app.get("/metrics")
    async def metrics_endpoint(request: Request) -> Response:
        token = request.headers.get("Authorization")
        if token != f"Bearer {settings.tokens.metrics_read}":
            raise HTTPException(status_code=401, detail="توکن نامعتبر است.")
        data = generate_latest(metrics.registry)
        return PlainTextResponse(data.decode("utf-8"))

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/readyz")
    async def readyz() -> PlainTextResponse:
        return PlainTextResponse("ready")

    return app


def get_debug_context(clock: Clock | None = None) -> dict[str, Any]:
    import os

    return {
        "redis_keys": [],
        "rate_limit_state": {},
        "middleware_order": [],
        "env": os.getenv("GITHUB_ACTIONS", "local"),
        "timestamp": clock.now().isoformat() if clock else None,
    }


__all__ = ["create_reliability_app", "RateLimitMiddleware", "IdempotencyMiddleware", "AuthMiddleware", "get_debug_context"]
