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
from fastapi.responses import HTMLResponse

# from sma.infrastructure.security.auth import require_roles # حذف شد
# from sma.infrastructure.security.rate_limit import RateLimiter # حذف شد
# from sma.interfaces.schemas import AllocationRunRequest, Job, JobStatus
# from sma.infrastructure.monitoring.logging_adapter import (
#     CorrelationIdMiddleware,
#     configure_json_logging,
# )
# فرض می‌کنیم CorrelationIdMiddleware در جای دیگری تعریف شده یا منتقل شده
from sma.infrastructure.monitoring.logging_adapter import CorrelationIdMiddleware # فرض بر این است که همچنان مورد نیاز است
from sma.infrastructure.monitoring.logging_adapter import configure_json_logging # فرض بر این است که همچنان مورد نیاز است
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sma.core.clock import Clock
from sma.web.deps.clock import provide_clock

# --- تغییر میدلویر RateLimit ---
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, limiter) -> None: # limiter دیگر مورد نیاز نیست
        super().__init__(app)
        # self._limiter = limiter # حذف شد

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # زنجیره میدلویر امنیتی حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # request.state.middleware_chain = chain + ["RateLimit"]
        # همیشه اجازه می‌دهد
        # key = request.headers.get("X-Api-Key") or (request.client.host if request.client else "anonymous")
        # try:
        #     allowed = self._limiter.allow(key)
        # except Exception as exc: ...
        # if not allowed: ...
        return await call_next(request) # تغییر داده شد


# --- تغییر میدلویر Idempotency ---
class _IdempotencyCache:
    # این کلاس دیگر مورد نیاز نیست، زیرا میدلویر از کار افتاده
    # می‌تواند حذف یا تغییر کند
    def __init__(self, ttl_seconds: int = 24 * 60 * 60) -> None:
        # self._ttl = ttl_seconds
        # self._store: dict[str, tuple[float, dict[str, object]]] = {}
        # self._lock = asyncio.Lock()
        pass # تغییر داده شد

    async def get(self, key: str) -> dict[str, object] | None:
        # now = time.monotonic()
        # async with self._lock: ...
        return None # تغییر داده شد

    async def set(self, key: str, payload: dict[str, object]) -> None:
        # expires_at = time.monotonic() + self._ttl
        # async with self._lock: ...
        pass # تغییر داده شد


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, cache) -> None: # cache دیگر مورد نیاز نیست
        super().__init__(app)
        # self._cache = cache # حذف شد

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # زنجیره میدلویر امنیتی حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # request.state.middleware_chain = chain + ["Idempotency"]
        # اگر متد POST/PUT/PATCH نبود، فقط ادامه می‌داد
        # if request.method.upper() not in {"POST", "PUT", "PATCH"}: ...
        # بررسی کلید ایدمپوتنسی حذف شد
        # key = request.headers.get("Idempotency-Key", "").strip()
        # if not (8 <= len(key) <= 128): ...
        # بررسی کش حذف شد
        # cached = await self._cache.get(key)
        # if cached: ...
        # ادامه مسیر را فراخوانی می‌کند و بدنه را ممکن است بخواند و ذخیره کند
        response: StarletteResponse = await call_next(request)
        # خواندن و ذخیره بدنه دیگر انجام نمی‌شود
        # body_bytes = b""
        # iterator = getattr(response, "body_iterator", None)
        # if iterator is not None: ...
        # elif getattr(response, "body", None) is not None: ...
        # response.body_iterator = iterate_in_threadpool([body_bytes])
        # await self._cache.set(...) # حذف شد
        # افزودن هدر زنجیره میدلویر حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # if chain: ...
        return response # تغییر داده شد


def _normalize_token(value: str | None) -> str:
    return value.strip() if value else ""


# --- تغییر میدلویر Auth ---
class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, metrics_token: str) -> None: # metrics_token دیگر مورد نیاز نیست
        super().__init__(app)
        # self._metrics_token = metrics_token # حذف شد

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # زنجیره میدلویر امنیتی حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # request.state.middleware_chain = chain + ["Auth"]
        # تمام چک‌های امنیتی حذف شدند
        # bypass = {"/readyz", "/healthz"}
        # method = request.method.upper()
        # is_ui = request.url.path == "/ui" and method in {"GET", "HEAD"}
        # if request.url.path in bypass or is_ui: ...
        # if request.url.path == "/metrics": ...
        # auth_header = _normalize_token(request.headers.get("Authorization"))
        # if not auth_header.startswith("Bearer "): ...
        # فقط ادامه مسیر را فراخوانی می‌کند
        response = await call_next(request)
        # افزودن هدر زنجیره میدلویر حذف شد
        # chain = getattr(request.state, "middleware_chain", [])
        # if chain: ...
        return response # تغییر داده شد


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
async def run_allocation(req: AllocationRunRequest): #, user=require_roles("alloc:run") # حذف شد
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
    # try:
    #     limiter = RateLimiter(limit=100, clock=system_clock)
    # except RuntimeError:
    #     class _NoopLimiter: ...
    #     limiter = _NoopLimiter()
    # idem_cache = _IdempotencyCache() # دیگر مورد نیاز نیست
    # metrics_token = _normalize_token(os.getenv("METRICS_TOKEN", "metrics-token")) # دیگر مورد نیاز نیست

    # افزودن میدلویرهای امنیتی حذف شد
    # app.add_middleware(AuthMiddleware, metrics_token=metrics_token)
    # app.add_middleware(IdempotencyMiddleware, cache=idem_cache)
    # app.add_middleware(RateLimitMiddleware, limiter=limiter)

    app.include_router(router)
    install_error_handlers(app)

    # تغییر endpoint /metrics
    @app.get("/metrics")
    async def metrics(request: Request):  # pragma: no cover - integration
        # چک توکن حذف شد
        # provided = _normalize_token(request.headers.get("X-Metrics-Token"))
        # if provided != metrics_token: ...
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/readyz")
    async def readyz():
        return {"status": "ok"}

    @app.head("/ui")
    async def ui_head() -> Response:
        return Response(status_code=200)

    @app.get("/ui", include_in_schema=False, response_class=HTMLResponse)
    async def ui_root() -> HTMLResponse:
        # Minimal SSR stub to satisfy Windows launcher WebView startup
        # while keeping /metrics token-guarded. Real UI can be plugged here.
        html = (
            """
            <!doctype html>
            <html lang="fa">
            <head>
                <meta charset="utf-8" />
                <title>سامانه تخصیص دانش‌آموز-مربی</title>
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; background:#0f1115; color:#e6e6e6; margin:0; }
                    header { padding: 16px 20px; background:#141821; border-bottom:1px solid #222838; }
                    main { padding: 20px; }
                    .card { background:#141821; border:1px solid #222838; border-radius:8px; padding:16px; max-width:720px }
                    code { background:#1b2030; padding:2px 6px; border-radius:4px }
                    a { color:#66ccff; text-decoration:none }
                </style>
            </head>
            <body>
                <header>سامانه تخصیص دانش‌آموز-مربی</header>
                <main>
                  <div class="card">
                    <p>بک‌اند فعال است. این نمای ابتدایی صرفاً برای راه‌اندازی Windows/WebView2 است.</p>
                    <ul>
                      <li>وضعیت: <code><a href="/readyz" target="_blank">/readyz</a></code></li>
                      <li>متریک‌ها (بدون توکن): <code>/metrics</code></li>
                    </ul>
                  </div>
                </main>
            </body>
            </html>
            """
        )
        return HTMLResponse(content=html)

    return app
