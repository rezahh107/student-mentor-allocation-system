from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Mapping

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

from .clock import Clock, build_system_clock
from .config import AppConfig, AuthConfig
from .errors import install_error_handlers
from .logging_config import configure_logging
from .middleware import (
    AuthMiddleware,
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from ..obs.metrics import ServiceMetrics, build_metrics, render_metrics
from ..xlsx.workflow import ImportToSabtWorkflow
from .probes import AsyncProbe, ProbeResult
from .timing import MonotonicTimer, Timer
from .stores import KeyValueStore
from .utils import normalize_token

logger = logging.getLogger(__name__)


@dataclass
class ApplicationContainer:
    config: AppConfig
    clock: Clock
    timer: Timer
    metrics: ServiceMetrics
    templates: Jinja2Templates
    rate_limit_store: KeyValueStore
    idempotency_store: KeyValueStore
    readiness_probes: Mapping[str, AsyncProbe]


async def _run_probe(name: str, probe: AsyncProbe, timeout: float) -> ProbeResult:
    result = await probe(timeout)
    logger.debug("probe.result", extra={"correlation_id": None, "component": name, "outcome": result.healthy})
    return result


def _build_templates() -> Jinja2Templates:
    return Jinja2Templates(directory="src/phase6_import_to_sabt/templates")


def configure_middleware(app: FastAPI, container: ApplicationContainer) -> None:
    app.add_middleware(RequestLoggingMiddleware, diagnostics=lambda: getattr(app.state, "diagnostics", None))
    app.add_middleware(MetricsMiddleware, metrics=container.metrics, timer=container.timer)
    app.add_middleware(
        AuthMiddleware,
        token=container.config.auth.service_token,
        metrics=container.metrics.middleware,
        timer=container.timer,
    )
    app.add_middleware(
        IdempotencyMiddleware,
        store=container.idempotency_store,
        metrics=container.metrics.middleware,
        timer=container.timer,
    )
    app.add_middleware(
        RateLimitMiddleware,
        store=container.rate_limit_store,
        config=container.config.ratelimit,
        clock=container.clock,
        metrics=container.metrics.middleware,
        timer=container.timer,
    )
    app.add_middleware(CorrelationIdMiddleware, clock=container.clock)


def create_application(
    config: AppConfig,
    *,
    clock: Clock | None = None,
    metrics: ServiceMetrics | None = None,
    timer: Timer | None = None,
    templates: Jinja2Templates | None = None,
    rate_limit_store: KeyValueStore,
    idempotency_store: KeyValueStore,
    readiness_probes: Mapping[str, AsyncProbe],
    workflow: ImportToSabtWorkflow | None = None,
) -> FastAPI:
    clock = clock or build_system_clock(config.timezone)
    metrics = metrics or build_metrics(config.observability.metrics_namespace)
    timer = timer or MonotonicTimer()
    templates = templates or _build_templates()

    configure_logging(config.observability.service_name, config.enable_debug_logs)

    container = ApplicationContainer(
        config=config,
        clock=clock,
        timer=timer,
        metrics=metrics,
        templates=templates,
        rate_limit_store=rate_limit_store,
        idempotency_store=idempotency_store,
        readiness_probes=readiness_probes,
    )

    app = FastAPI(title="ImportToSabt")
    app.mount("/static", StaticFiles(directory="assets"), name="static")
    app.state.diagnostics = {
        "enabled": config.enable_diagnostics,
        "last_chain": [],
        "last_rate_limit": None,
        "last_idempotency": None,
        "last_auth": None,
    }
    install_error_handlers(app)
    configure_middleware(app, container)

    @app.middleware("http")
    async def record_request_time(request: Request, call_next):
        response = await call_next(request)
        return response

    @app.get("/healthz")
    async def healthz(request: Request):
        results = []
        for name, probe in container.readiness_probes.items():
            result = await _run_probe(name, probe, container.config.health_timeout_seconds)
            container.metrics.readiness_total.labels(component=name, status="healthy" if result.healthy else "degraded").inc()
            results.append(result)
        return {
            "status": "ok",
            "checked_at": container.clock.now().isoformat(),
            "components": [result.__dict__ for result in results],
        }

    @app.get("/readyz")
    async def readyz(request: Request):
        results = []
        ready = True
        for name, probe in container.readiness_probes.items():
            result = await _run_probe(name, probe, container.config.readiness_timeout_seconds)
            container.metrics.readiness_total.labels(component=name, status="ready" if result.healthy else "error").inc()
            results.append(result)
            ready &= result.healthy
        status_code = 200 if ready else 503
        payload = {
            "status": "ready" if ready else "not_ready",
            "checked_at": container.clock.now().isoformat(),
            "components": [result.__dict__ for result in results],
        }
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/metrics")
    async def metrics_endpoint(request: Request):
        supplied = normalize_token(request.headers.get("X-Metrics-Token"))
        if supplied != normalize_token(container.config.auth.metrics_token):
            return JSONResponse(
                status_code=401,
                content={
                    "fa_error_envelope": {
                        "code": "METRICS_TOKEN_INVALID",
                        "message": "توکن دسترسی به متریک معتبر نیست.",
                    }
                },
            )
        return PlainTextResponse(render_metrics(container.metrics).decode("utf-8"))

    @app.get("/ui/health", response_class=HTMLResponse)
    async def ui_health(request: Request):
        return container.templates.TemplateResponse(request, "health.html", {"title": "سلامت سامانه"})

    @app.get("/ui/exports", response_class=HTMLResponse)
    async def ui_exports(request: Request):
        return container.templates.TemplateResponse(request, "exports.html", {"title": "خروجی‌ها"})

    @app.get("/ui/exports/new", response_class=HTMLResponse)
    async def ui_exports_new(request: Request):
        return container.templates.TemplateResponse(request, "exports_new.html", {"title": "خروجی XLSX"})

    @app.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
    async def ui_job(request: Request, job_id: str):
        return container.templates.TemplateResponse(request, "job_detail.html", {"title": "جزئیات کار", "job_id": job_id})

    @app.get("/ui/uploads", response_class=HTMLResponse)
    async def ui_uploads(request: Request):
        return container.templates.TemplateResponse(request, "uploads.html", {"title": "بارگذاری فایل"})

    @app.get("/api/jobs")
    async def list_jobs(request: Request):
        return {"jobs": []}

    @app.post("/api/jobs")
    async def create_job(request: Request):
        chain = getattr(request.state, "middleware_chain", [])
        return {
            "processed": True,
            "correlation_id": getattr(request.state, "correlation_id", ""),
            "middleware_chain": chain,
        }

    @app.get("/api/exports/csv")
    async def exporter_stub() -> dict[str, str]:
        return {"status": "queued"}

    if workflow is not None:
        from ..xlsx.router import build_router as build_xlsx_router

        app.include_router(build_xlsx_router(workflow))

    if config.enable_diagnostics:

        @app.get("/__diag")
        async def diagnostics() -> dict[str, object]:
            return app.state.diagnostics

    return app


__all__ = ["ApplicationContainer", "create_application", "configure_middleware"]
