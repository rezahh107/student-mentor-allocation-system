# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.concurrency import iterate_in_threadpool

from fastapi import APIRouter, FastAPI, File, UploadFile, Response
from fastapi.responses import JSONResponse

from application.commands.allocation import GetJobStatus, StartBatchAllocation
from infrastructure.api.error_handlers import install_error_handlers
from infrastructure.security.auth import require_roles
from infrastructure.security.rate_limit import RateLimiter
from interfaces.schemas import AllocationRunRequest, Job, JobStatus
from infrastructure.monitoring.logging_adapter import (
    CorrelationIdMiddleware,
    configure_json_logging,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.core.clock import Clock
from src.web.deps.clock import provide_clock


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, limiter: RateLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        chain = getattr(request.state, "middleware_chain", [])
        request.state.middleware_chain = chain + ["RateLimit"]
        key = request.headers.get("X-Api-Key") or (request.client.host if request.client else "anonymous")
        try:
            allowed = self._limiter.allow(key)
        except Exception as exc:  # pragma: no cover - defensive
            logging.getLogger(__name__).warning("rate_limit_error", extra={"error": str(exc)})
            allowed = True
        if not allowed:
            return StarletteJSONResponse(
                status_code=429,
                content={"fa_error_envelope": {"code": "RATE_LIMIT", "message": "تعداد درخواست بیش از حد مجاز است."}},
                headers={"Retry-After": "60"},
            )
        return await call_next(request)


class _IdempotencyCache:
    def __init__(self, ttl_seconds: int = 24 * 60 * 60) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, object]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> dict[str, object] | None:
        now = time.monotonic()
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, payload = entry
            if expires_at < now:
                del self._store[key]
                return None
            return payload

    async def set(self, key: str, payload: dict[str, object]) -> None:
        expires_at = time.monotonic() + self._ttl
        async with self._lock:
            self._store[key] = (expires_at, payload)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, cache: _IdempotencyCache) -> None:
        super().__init__(app)
        self._cache = cache

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        chain = getattr(request.state, "middleware_chain", [])
        request.state.middleware_chain = chain + ["Idempotency"]
        if request.method.upper() not in {"POST", "PUT", "PATCH"}:
            return await call_next(request)
        key = request.headers.get("Idempotency-Key", "").strip()
        if not (8 <= len(key) <= 128):
            return StarletteJSONResponse(
                status_code=400,
                content={"fa_error_envelope": {"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "کلید ایدمپوتنسی نامعتبر است."}},
            )
        cached = await self._cache.get(key)
        if cached:
            body = cached.get("body", b"")
            if isinstance(body, str):
                body_bytes = body.encode("utf-8")
            else:
                body_bytes = body  # type: ignore[assignment]
            response = StarletteResponse(
                content=body_bytes,
                status_code=int(cached.get("status", 200)),
                headers=cached.get("headers", {}),
                media_type=cached.get("media_type", "application/json"),
            )
            chain = getattr(request.state, "middleware_chain", [])
            if chain:
                response.headers["X-Middleware-Chain"] = ",".join(chain)
            return response

        response: StarletteResponse = await call_next(request)
        body_bytes = b""
        iterator = getattr(response, "body_iterator", None)
        if iterator is not None:
            async for chunk in iterator:
                body_bytes += chunk
        elif getattr(response, "body", None) is not None:
            body_bytes = response.body  # type: ignore[assignment]
        response.body_iterator = iterate_in_threadpool([body_bytes])
        await self._cache.set(
            key,
            {
                "status": response.status_code,
                "headers": {k: v for k, v in response.headers.items() if k.lower().startswith("x-")},
                "body": body_bytes,
                "media_type": response.media_type or "application/json",
            },
        )
        chain = getattr(request.state, "middleware_chain", [])
        if chain:
            response.headers["X-Middleware-Chain"] = ",".join(chain)
        return response


def _normalize_token(value: str | None) -> str:
    return value.strip() if value else ""


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, metrics_token: str) -> None:
        super().__init__(app)
        self._metrics_token = metrics_token

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        chain = getattr(request.state, "middleware_chain", [])
        request.state.middleware_chain = chain + ["Auth"]
        if request.url.path in {"/readyz", "/healthz"}:
            response = await call_next(request)
            chain = getattr(request.state, "middleware_chain", [])
            if chain:
                response.headers["X-Middleware-Chain"] = ",".join(chain)
            return response
        if request.method.upper() == "HEAD" and request.url.path == "/ui":
            response = await call_next(request)
            chain = getattr(request.state, "middleware_chain", [])
            if chain:
                response.headers["X-Middleware-Chain"] = ",".join(chain)
            return response
        if request.url.path == "/metrics":
            provided = _normalize_token(request.headers.get("X-Metrics-Token"))
            if not provided or provided != self._metrics_token:
                return StarletteJSONResponse(
                    status_code=401,
                    content={"fa_error_envelope": {"code": "METRICS_FORBIDDEN", "message": "توکن متریک نامعتبر است."}},
                    headers={"X-Middleware-Chain": ",".join(request.state.middleware_chain)},
                )
            response = await call_next(request)
            chain = getattr(request.state, "middleware_chain", [])
            if chain:
                response.headers["X-Middleware-Chain"] = ",".join(chain)
            return response

        auth_header = _normalize_token(request.headers.get("Authorization"))
        if not auth_header.startswith("Bearer "):
            return StarletteJSONResponse(
                status_code=401,
                content={"fa_error_envelope": {"code": "UNAUTHORIZED", "message": "توکن الزامی است."}},
            )
        response = await call_next(request)
        chain = getattr(request.state, "middleware_chain", [])
        if chain:
            response.headers["X-Middleware-Chain"] = ",".join(chain)
        return response


router = APIRouter(prefix="/api/v1")


@router.post("/students/import", response_model=Job, status_code=202)
async def import_students(file: UploadFile = File(...)):
    # Basic file validation
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        return JSONResponse(status_code=400, content={"error": "INVALID_FILE", "message": "Only .xlsx/.xls accepted"})
    if file.content_type not in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/octet-stream",
    ):
        return JSONResponse(status_code=400, content={"error": "INVALID_MIME", "message": "Unsupported content-type"})
    # Placeholder: store file, create job, enqueue ingestion
    return Job(jobId="job-import-1", status="pending")


@router.post("/allocation/run", response_model=Job, status_code=202)
async def run_allocation(req: AllocationRunRequest, user=require_roles("alloc:run")):
    # Placeholder: start batch allocation via service
    _cmd = StartBatchAllocation(priority_mode=req.priority_mode, guarantee_assignment=req.guarantee_assignment)
    return Job(jobId="job-alloc-1", status="running")


@router.get("/allocation/status/{job_id}", response_model=JobStatus)
async def allocation_status(job_id: str):
    # Placeholder: return job status
    _q = GetJobStatus(job_id=job_id)
    return JobStatus(jobId=job_id, status="completed", progress=100, totals={"processed": 0, "successful": 0, "failed": 0})


@router.get("/reports/export")
async def export_report():
    # Placeholder: return a link or generated file handle
    return JSONResponse({"ok": True})


def create_app() -> FastAPI:
    configure_json_logging()
    app = FastAPI(title="Student-Mentor Allocation API", version="1.0")
    app.add_middleware(CorrelationIdMiddleware)

    system_clock: Clock = provide_clock()
    try:
        limiter = RateLimiter(limit=100, clock=system_clock)
    except RuntimeError:
        class _NoopLimiter:
            def allow(self, key: str) -> bool:  # noqa: D401 - simple stub
                return True

        limiter = _NoopLimiter()
    idem_cache = _IdempotencyCache()
    metrics_token = _normalize_token(os.getenv("METRICS_TOKEN", "metrics-token"))

    app.add_middleware(AuthMiddleware, metrics_token=metrics_token)
    app.add_middleware(IdempotencyMiddleware, cache=idem_cache)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    app.include_router(router)
    install_error_handlers(app)

    @app.get("/metrics")
    async def metrics(request: Request):  # pragma: no cover - integration
        provided = _normalize_token(request.headers.get("X-Metrics-Token"))
        if provided != metrics_token:
            return JSONResponse(
                status_code=401,
                content={"fa_error_envelope": {"code": "METRICS_FORBIDDEN", "message": "توکن متریک نامعتبر است."}},
            )
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/readyz")
    async def readyz():
        return {"status": "ok"}

    @app.head("/ui")
    async def ui_head() -> Response:
        return Response(status_code=200)

    return app
