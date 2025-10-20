from __future__ import annotations

import logging
from dataclasses import dataclass
import os
import unicodedata
import importlib.resources as resources
from pathlib import Path
from typing import Mapping

ZERO_WIDTH = {"\u200c", "\u200d", "\ufeff", "\u2060"}

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

from sma.phase6_import_to_sabt.app.clock import Clock, build_system_clock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.errors import install_error_handlers
from sma.phase6_import_to_sabt.app.logging_config import configure_logging
from sma.phase6_import_to_sabt.app.middleware import (
    AuthMiddleware,
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
    MetricsMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
)
from sma.phase6_import_to_sabt.download_api import (
    DownloadMetrics,
    DownloadRetryPolicy,
    DownloadSettings,
    SignatureSecurityConfig,
    SignatureSecurityManager,
    create_download_router,
)
from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics, build_metrics, render_metrics
from sma.phase6_import_to_sabt.observability import MetricsCollector, profile_endpoint, trace_span
from sma.phase6_import_to_sabt.security.config import AccessConfigGuard, ConfigGuardError, SigningKeyDefinition, TokenDefinition
from sma.phase6_import_to_sabt.security.rbac import TokenRegistry
from sma.phase6_import_to_sabt.security.signer import DualKeySigner, SignatureError, SigningKeySet
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow
from sma.phase6_import_to_sabt.app.probes import AsyncProbe, ProbeResult
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore, KeyValueStore
from sma.phase6_import_to_sabt.app.timing import MonotonicTimer, Timer
from sma.phase6_import_to_sabt.app.utils import normalize_token

logger = logging.getLogger(__name__)


@dataclass
class ApplicationContainer:
    config: AppConfig
    clock: Clock
    timer: Timer
    metrics: ServiceMetrics
    metrics_collector: MetricsCollector
    download_metrics: DownloadMetrics
    download_settings: DownloadSettings
    signature_security: SignatureSecurityManager
    templates: Jinja2Templates
    rate_limit_store: KeyValueStore
    idempotency_store: KeyValueStore
    readiness_probes: Mapping[str, AsyncProbe]
    token_registry: TokenRegistry
    download_signer: DualKeySigner
    metrics_token: str | None
    metrics_token_error: str | None
    metrics_token_source: str | None


async def _run_probe(name: str, probe: AsyncProbe, timeout: float) -> ProbeResult:
    result = await probe(timeout)
    logger.debug("probe.result", extra={"correlation_id": None, "component": name, "outcome": result.healthy})
    return result


def _build_templates() -> Jinja2Templates:
    templates_dir = resources.files("phase6_import_to_sabt").joinpath("templates")
    return Jinja2Templates(directory=str(templates_dir))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_static_assets_root() -> Path:
    project_root = _project_root()
    candidate = project_root / "assets"
    if candidate.exists():
        return candidate
    return Path.cwd() / "assets"


def _normalize_storage_text(value: str | os.PathLike[str] | None) -> str:
    if value is None:
        return ""
    raw = str(value)
    normalized = unicodedata.normalize("NFKC", raw)
    for marker in ZERO_WIDTH:
        normalized = normalized.replace(marker, "")
    normalized = normalized.strip()
    return normalized


def _resolve_storage_root(
    *,
    workflow: ImportToSabtWorkflow | None,
    env: Mapping[str, str] | None = None,
) -> Path:
    if workflow is not None:
        return Path(workflow.storage_dir).resolve()

    env_mapping = dict(env or os.environ)
    explicit = _normalize_storage_text(env_mapping.get("EXPORT_STORAGE_DIR"))
    project_root = _project_root()
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    default_root = project_root / "storage" / "exports"
    return default_root.resolve()


def configure_middleware(app: FastAPI, container: ApplicationContainer) -> None:
    app.add_middleware(CorrelationIdMiddleware, clock=container.clock)
    ordered_middlewares = [
        (
            RateLimitMiddleware,
            {
                "store": container.rate_limit_store,
                "config": container.config.ratelimit,
                "clock": container.clock,
                "metrics": container.metrics.middleware,
                "timer": container.timer,
            },
        ),
        (
            IdempotencyMiddleware,
            {
                "store": container.idempotency_store,
                "metrics": container.metrics.middleware,
                "timer": container.timer,
                "clock": container.clock,
            },
        ),
        (
            AuthMiddleware,
            {
                "token_registry": container.token_registry,
                "metrics": container.metrics.middleware,
                "timer": container.timer,
                "service_metrics": container.metrics,
            },
        ),
    ]
    for middleware_cls, kwargs in reversed(ordered_middlewares):
        app.add_middleware(middleware_cls, **kwargs)
    app.add_middleware(MetricsMiddleware, metrics=container.metrics, timer=container.timer)
    app.add_middleware(RequestLoggingMiddleware, diagnostics=lambda: getattr(app.state, "diagnostics", None))


def create_application(
    config: AppConfig | None = None,
    *,
    clock: Clock | None = None,
    metrics: ServiceMetrics | None = None,
    timer: Timer | None = None,
    templates: Jinja2Templates | None = None,
    rate_limit_store: KeyValueStore | None = None,
    idempotency_store: KeyValueStore | None = None,
    readiness_probes: Mapping[str, AsyncProbe] | None = None,
    workflow: ImportToSabtWorkflow | None = None,
) -> FastAPI:
    config = config or AppConfig.from_env()
    clock = clock or build_system_clock(config.timezone)
    metrics = metrics or build_metrics(config.observability.metrics_namespace)
    timer = timer or MonotonicTimer()
    templates = templates or _build_templates()
    rate_limit_store = rate_limit_store or InMemoryKeyValueStore(
        f"{config.ratelimit.namespace}:rate", clock
    )
    idempotency_store = idempotency_store or InMemoryKeyValueStore(
        f"{config.ratelimit.namespace}:idempotency", clock
    )
    readiness_probes = dict(readiness_probes or {})

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
    env_metrics_token = normalize_token(os.environ.get("METRICS_TOKEN"))
    metrics_token_source: str | None = None
    metrics_token_error: str | None = None
    metrics_token: str | None = None

    if env_metrics_token:
        metrics_token = _add_token(env_metrics_token, "METRICS_RO", metrics_only=True)
        metrics_token_source = "env:METRICS_TOKEN"
    elif access and access.metrics_tokens:
        metrics_token = _add_token(access.metrics_tokens[0], "METRICS_RO", metrics_only=True)
        metrics_token_source = f"env:{config.auth.tokens_env_var}"
    else:
        metrics_token = _add_token(
            config.auth.metrics_token,
            "METRICS_RO",
            metrics_only=True,
        )
        if metrics_token:
            metrics_token_source = "config:IMPORT_TO_SABT_AUTH__METRICS_TOKEN"

    if not metrics_token:
        metrics_token_error = "«پیکربندی ناقص است؛ متغیر METRICS_TOKEN یا IMPORT_TO_SABT_AUTH__METRICS_TOKEN را مقداردهی کنید.»"
        logger.warning(
            "metrics.token.missing",
            extra={
                "correlation_id": None,
                "source_env": bool(env_metrics_token),
                "tokens_env": bool(access and access.metrics_tokens),
            },
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

    storage_root = _resolve_storage_root(workflow=workflow)
    storage_root.mkdir(parents=True, exist_ok=True)
    download_secret = normalize_token(config.auth.service_token) or "import-to-sabt-download"
    download_settings = DownloadSettings(
        workspace_root=storage_root,
        secret=download_secret.encode("utf-8"),
        retry=DownloadRetryPolicy(),
    )
    download_metrics = DownloadMetrics(metrics.registry)
    metrics_collector = MetricsCollector(metrics.registry)
    security_config = SignatureSecurityConfig()
    signature_security = SignatureSecurityManager(
        clock=clock,
        config=security_config,
        observer=metrics_collector,
    )

    container = ApplicationContainer(
        config=config,
        clock=clock,
        timer=timer,
        metrics=metrics,
        metrics_collector=metrics_collector,
        download_metrics=download_metrics,
        download_settings=download_settings,
        signature_security=signature_security,
        templates=templates,
        rate_limit_store=rate_limit_store,
        idempotency_store=idempotency_store,
        readiness_probes=readiness_probes,
        token_registry=token_registry,
        download_signer=signer,
        metrics_token=metrics_token,
        metrics_token_error=metrics_token_error,
        metrics_token_source=metrics_token_source,
    )

    app = FastAPI(title="ImportToSabt")
    static_root = _resolve_static_assets_root()
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=str(static_root)), name="static")
    app.state.diagnostics = {
        "enabled": config.enable_diagnostics,
        "last_chain": [],
        "last_rate_limit": None,
        "last_idempotency": None,
        "last_auth": None,
        "metrics_token_source": metrics_token_source,
        "metrics_token_error": metrics_token_error,
    }
    app.state.storage_root = storage_root
    app.state.download_metrics = download_metrics
    app.state.metrics_collector = metrics_collector
    app.state.signature_security = signature_security

    def _legacy_forbidden(
        message: str,
        *,
        correlation_id: str | None,
        reason: str,
    ) -> JSONResponse:
        download_metrics.requests_total.labels(status="legacy_forbidden").inc()
        download_metrics.invalid_token_total.inc()
        logger.warning(
            "download.legacy_forbidden",
            extra={"correlation_id": correlation_id, "reason": reason},
        )
        return JSONResponse(
            status_code=403,
            content={
                "fa_error_envelope": {
                    "code": "DOWNLOAD_FORBIDDEN",
                    "message": message,
                }
            },
        )

    async def _record_legacy_failure(
        request: Request,
        *,
        reason: str,
        message: str,
    ) -> JSONResponse:
        collector: MetricsCollector | None = getattr(request.app.state, "metrics_collector", None)
        security: SignatureSecurityManager | None = getattr(request.app.state, "signature_security", None)
        client_id = request.client.host if request.client else "anonymous"
        correlation_id = getattr(request.state, "correlation_id", None)
        if collector is not None:
            collector.record_signature_failure(reason=reason)
        if security is not None:
            blocked = await security.record_failure(client_id, reason=reason)
            if blocked:
                download_metrics.requests_total.labels(status="blocked").inc()
                return JSONResponse(
                    status_code=429,
                    content={
                        "fa_error_envelope": {
                            "code": "DOWNLOAD_TEMPORARILY_BLOCKED",
                            "message": "دسترسی موقتاً مسدود شد.",
                        }
                    },
                    headers={"X-Request-ID": correlation_id or "download-blocked"},
                )
        return _legacy_forbidden(message, correlation_id=correlation_id, reason=reason)

    download_router = create_download_router(
        settings=download_settings,
        clock=clock,
        metrics=download_metrics,
        observer=metrics_collector,
        security=signature_security,
    )
    app.include_router(download_router)

    @app.get("/download")
    async def download_endpoint(
        signed: str,
        kid: str,
        exp: int,
        sig: str,
        request: Request,
    ) -> Response:
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

        base_dir_value = getattr(request.app.state, "storage_root", None)
        if not base_dir_value:
            return JSONResponse(
                status_code=503,
                content={
                    "fa_error_envelope": {
                        "code": "DOWNLOAD_UNAVAILABLE",
                        "message": "سرویس دانلود در دسترس نیست.",
                    }
                },
            )

        base_dir = Path(base_dir_value).resolve()
        if not base_dir.exists():
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
        try:
            target.relative_to(base_dir)
        except ValueError:
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
        if not expected_token:
            container.metrics.auth_fail_total.labels(reason="metrics_missing").inc()
            message = container.metrics_token_error or "توکن متریک تنظیم نشده است."
            return JSONResponse(
                status_code=403,
                content={
                    "fa_error_envelope": {
                        "code": "METRICS_TOKEN_MISSING",
                        "message": message,
                    }
                },
            )
        if actor is None or not actor.metrics_only or provided_token != expected_token:
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
        from sma.phase6_import_to_sabt.xlsx.router import build_router as build_xlsx_router

        app.include_router(build_xlsx_router(workflow))

    if config.enable_diagnostics:

        @app.get("/__diag")
        async def diagnostics() -> dict[str, object]:
            return app.state.diagnostics

    return app


build_app = create_application
create_app = create_application


__all__ = [
    "ApplicationContainer",
    "create_application",
    "configure_middleware",
    "build_app",
    "create_app",
]
