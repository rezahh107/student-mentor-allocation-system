from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
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
from ..security.config import AccessConfigGuard, ConfigGuardError, SigningKeyDefinition, TokenDefinition
from ..security.rbac import TokenRegistry
from ..security.signer import DualKeySigner, SignatureError, SigningKeySet
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
    token_registry: TokenRegistry
    download_signer: DualKeySigner
    metrics_token: str | None


async def _run_probe(name: str, probe: AsyncProbe, timeout: float) -> ProbeResult:
    result = await probe(timeout)
    logger.debug("probe.result", extra={"correlation_id": None, "component": name, "outcome": result.healthy})
    return result


def _build_templates() -> Jinja2Templates:
    return Jinja2Templates(directory="src/phase6_import_to_sabt/templates")


def configure_middleware(app: FastAPI, container: ApplicationContainer) -> None:
    app.add_middleware(CorrelationIdMiddleware, clock=container.clock)
    app.add_middleware(
        AuthMiddleware,
        token_registry=container.token_registry,
        metrics=container.metrics.middleware,
        timer=container.timer,
        service_metrics=container.metrics,
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
    app.add_middleware(MetricsMiddleware, metrics=container.metrics, timer=container.timer)
    app.add_middleware(RequestLoggingMiddleware, diagnostics=lambda: getattr(app.state, "diagnostics", None))


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

    guard = AccessConfigGuard()
    try:
        access = guard.load(
            tokens_env=config.auth.tokens_env_var,
            signing_keys_env=config.auth.download_signing_keys_env_var,
            download_ttl_seconds=config.auth.download_url_ttl_seconds,
        )
    except ConfigGuardError as exc:
        logger.warning("access.config.invalid", extra={"error": str(exc)})
        access = None

    tokens: list[TokenDefinition] = list(access.tokens) if access else []

    def _add_token(value: str, role: str, *, center: int | None = None, metrics_only: bool = False) -> str | None:
        normalized = normalize_token(value)
        if not normalized:
            return None
        if any(item.value == normalized for item in tokens):
            return normalized
        token_role = "METRICS_RO" if metrics_only else role
        scope = None if metrics_only else center
        tokens.append(TokenDefinition(normalized, token_role, scope, metrics_only))
        return normalized

    service_token = _add_token(config.auth.service_token, "ADMIN")
    if access and access.metrics_tokens:
        metrics_token = access.metrics_tokens[0]
    else:
        metrics_token = _add_token(
            config.auth.metrics_token,
            "METRICS_RO",
            metrics_only=True,
        )

    if not tokens:
        fallback_token = service_token or "local-service-token"
        tokens.append(TokenDefinition(fallback_token, "ADMIN", None, False))

    token_registry = TokenRegistry(tokens)

    signing_keys = list(access.signing_keys) if access else []
    if not signing_keys:
        fallback_secret = normalize_token(config.auth.service_token) or "import-to-sabt-secret"
        signing_keys = [SigningKeyDefinition("legacy", fallback_secret, "active")]

    signer = DualKeySigner(
        keys=SigningKeySet(signing_keys),
        clock=clock,
        metrics=metrics,
        default_ttl_seconds=access.download_ttl_seconds if access else config.auth.download_url_ttl_seconds,
    )

    container = ApplicationContainer(
        config=config,
        clock=clock,
        timer=timer,
        metrics=metrics,
        templates=templates,
        rate_limit_store=rate_limit_store,
        idempotency_store=idempotency_store,
        readiness_probes=readiness_probes,
        token_registry=token_registry,
        download_signer=signer,
        metrics_token=metrics_token or service_token,
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
    app.state.storage_root = Path(getattr(workflow, "storage_dir", Path("."))).resolve() if workflow else None
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
        actor = getattr(request.state, "actor", None)
        provided_token = normalize_token(request.headers.get("X-Metrics-Token"))
        expected_token = container.metrics_token
        if actor is None or not actor.metrics_only or not expected_token or provided_token != expected_token:
            container.metrics.auth_fail_total.labels(reason="metrics_forbidden").inc()
            return JSONResponse(
                status_code=403,
                content={
                    "fa_error_envelope": {
                        "code": "METRICS_TOKEN_INVALID",
                        "message": "توکن دسترسی به متریک معتبر نیست.",
                    }
                },
            )
        return PlainTextResponse(render_metrics(container.metrics).decode("utf-8"))

    @app.get("/download")
    async def download_endpoint(signed: str, kid: str, exp: int, sig: str) -> Response:
        try:
            relative_path = container.download_signer.verify_components(
                signed=signed,
                kid=kid,
                exp=exp,
                sig=sig,
                now=container.clock.now(),
            )
        except SignatureError as exc:
            return JSONResponse(
                status_code=403,
                content={
                    "fa_error_envelope": {
                        "code": "DOWNLOAD_FORBIDDEN",
                        "message": exc.message_fa,
                    }
                },
            )
        base_dir = app.state.storage_root
        if base_dir is None:
            return JSONResponse(
                status_code=503,
                content={
                    "fa_error_envelope": {
                        "code": "DOWNLOAD_UNAVAILABLE",
                        "message": "سرویس دانلود در دسترس نیست.",
                    }
                },
            )
        target = (base_dir / Path(relative_path)).resolve()
        if not str(target).startswith(str(base_dir)):
            container.metrics.download_signed_total.labels(outcome="path_violation").inc()
            return JSONResponse(
                status_code=403,
                content={
                    "fa_error_envelope": {
                        "code": "DOWNLOAD_FORBIDDEN",
                        "message": "توکن نامعتبر است.",
                    }
                },
            )
        if not target.is_file():
            container.metrics.download_signed_total.labels(outcome="missing").inc()
            return JSONResponse(
                status_code=404,
                content={
                    "fa_error_envelope": {
                        "code": "DOWNLOAD_NOT_FOUND",
                        "message": "فایل موردنظر یافت نشد.",
                    }
                },
            )
        container.metrics.download_signed_total.labels(outcome="served").inc()
        return FileResponse(target, filename=target.name)

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
        try:
            workflow._signed_urls = container.download_signer  # type: ignore[attr-defined]
            workflow._signed_url_ttl = access.download_ttl_seconds if access else config.auth.download_url_ttl_seconds  # type: ignore[attr-defined]
        except AttributeError:
            logger.debug("workflow.signed_url_override_failed")
        from ..xlsx.router import build_router as build_xlsx_router

        app.include_router(build_xlsx_router(workflow))

    if config.enable_diagnostics:

        @app.get("/__diag")
        async def diagnostics() -> dict[str, object]:
            return app.state.diagnostics

    return app


__all__ = ["ApplicationContainer", "create_application", "configure_middleware"]
