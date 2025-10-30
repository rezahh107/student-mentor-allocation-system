from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import importlib.resources as resources
import unicodedata

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

from sma.phase6_import_to_sabt.api import ExportAPI
from sma.phase6_import_to_sabt.app.clock import Clock, build_system_clock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.errors import install_error_handlers
from sma.phase6_import_to_sabt.app.logging_config import configure_logging
from sma.phase6_import_to_sabt.app.middleware import (
    # AuthMiddleware, # حذف شد
    CorrelationIdMiddleware,
    # IdempotencyMiddleware, # حذف شد
    MetricsMiddleware,
    RequestLoggingMiddleware,
    # RateLimitMiddleware, # حذف شد
)
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore, KeyValueStore
# from sma.phase6_import_to_sabt.download_api import ( # حذف شد
#     DownloadMetrics,
#     DownloadRetryPolicy,
#     DownloadSettings,
#     SignatureSecurityConfig,
#     SignatureSecurityManager,
#     create_download_router,
# )
from sma.phase6_import_to_sabt.exporter import ImportToSabtExporter
from sma.phase6_import_to_sabt.data_source import InMemoryDataSource
from sma.phase6_import_to_sabt.job_runner import ExportJobRunner
from sma.phase6_import_to_sabt.logging_utils import ExportLogger
from sma.phase6_import_to_sabt.metrics import ExporterMetrics
from sma.phase6_import_to_sabt.obs.metrics import ServiceMetrics, build_metrics, render_metrics
from sma.phase6_import_to_sabt.observability import MetricsCollector
# from sma.phase6_import_to_sabt.models import SignedURLProvider # حذف شد
# from sma.phase6_import_to_sabt.roster import InMemoryRoster # احتمالاً هنوز مورد نیاز است
from sma.phase6_import_to_sabt.app.probes import AsyncProbe, ProbeResult
from sma.phase6_import_to_sabt.app.timing import MonotonicTimer, Timer
from sma.phase6_import_to_sabt.app.utils import normalize_token # ممکن است هنوز مورد نیاز باشد
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow
# from sma.phase6_import_to_sabt.security import AuthenticatedActor # حذف شد
# from sma.phase6_import_to_sabt.security.config import AccessConfigGuard, ConfigGuardError, SigningKeyDefinition, TokenDefinition # حذف شد
# from sma.phase6_import_to_sabt.security.rbac import ( # حذف شد
#     AuthorizationError,
#     TokenRegistry,
#     enforce_center_scope,
# )
# from sma.phase6_import_to_sabt.security.signer import DualKeySigner, SignatureError, SigningKeySet # حذف شد
# from sma.phase7_release.deploy import ReadinessGate # احتمالاً هنوز مورد نیاز است


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}

logger = logging.getLogger(__name__)

# ApplicationContainer باید بخش‌های امنیتی حذف شوند
@dataclass
class ApplicationContainer:
    config: AppConfig
    clock: Clock
    timer: Timer
    metrics: ServiceMetrics
    metrics_collector: MetricsCollector
    # download_metrics: DownloadMetrics # حذف شد
    # download_settings: DownloadSettings # حذف شد
    # signature_security: SignatureSecurityManager # حذف شد
    templates: Jinja2Templates
    # rate_limit_store: KeyValueStore # حذف شد
    # idempotency_store: KeyValueStore # حذف شد
    readiness_probes: Mapping[str, AsyncProbe]
    # token_registry: TokenRegistry # حذف شد
    # download_signer: DualKeySigner # حذف شد
    # metrics_token: str | None # حذف شد
    # metrics_token_error: str | None # حذف شد
    # metrics_token_source: str | None # حذف شد
    # اضافه کردن موارد جدید اگر نیاز باشد
    storage_root: Path
    export_runner: ExportJobRunner
    export_metrics: ExporterMetrics
    export_logger: ExportLogger
    # export_signer: SignedURLProvider # حذف شد یا تغییر کرد


async def _run_probe(name: str, probe: AsyncProbe, timeout: float) -> ProbeResult:
    result = await probe(timeout)
    # تغییر کردن `correlation_id` به None یا حذف آن اگر دیگر استفاده نشود
    logger.debug("probe.result", extra={"correlation_id": None, "component": name, "outcome": result.healthy})
    return result


def _build_templates() -> Jinja2Templates:
    templates_dir = resources.files("sma.phase6_import_to_sabt").joinpath("templates")
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
    for marker in {"\u200c", "\u200d", "\ufeff", "\u2060"}: # ZERO_WIDTH مستقیماً درج شد
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


def _build_default_export_runner(
    *,
    storage_root: Path,
    clock: Clock,
    metrics: ExporterMetrics,
    logger: ExportLogger,
) -> ExportJobRunner:
    exports_root = storage_root.resolve()
    exports_root.mkdir(parents=True, exist_ok=True)
    data_source = InMemoryDataSource([])
    # از sma.phase6_import_to_sabt.roster import InMemoryRoster # اگر هنوز مورد نیاز است
    from sma.phase6_import_to_sabt.roster import InMemoryRoster
    roster = InMemoryRoster({})
    exporter = ImportToSabtExporter(
        data_source=data_source,
        roster=roster,
        output_dir=exports_root,
        metrics=metrics,
        clock=clock,
    )
    return ExportJobRunner(exporter=exporter, metrics=metrics, logger=logger, clock=clock)


# configure_middleware باید فقط میدلویرهای غیر امنیتی را اضافه کند
def configure_middleware(app: FastAPI, container: ApplicationContainer) -> None:
    app.add_middleware(CorrelationIdMiddleware, clock=container.clock)
    # ترتیب میدلویرهای امنیتی حذف شد
    # ordered_middlewares = [
    #     (
    #         RateLimitMiddleware,
    #         { ... }
    #     ),
    #     (
    #         IdempotencyMiddleware,
    #         { ... }
    #     ),
    #     (
    #         AuthMiddleware,
    #         { ... }
    #     ),
    # ]
    # for middleware_cls, kwargs in reversed(ordered_middlewares):
    #     app.add_middleware(middleware_cls, **kwargs)
    app.add_middleware(MetricsMiddleware, metrics=container.metrics, timer=container.timer)
    app.add_middleware(RequestLoggingMiddleware, diagnostics=lambda: getattr(app.state, "diagnostics", None))


# تابع `_require_actor` و توابع مربوط به UI حذف می‌شوند
# def _require_actor(request: Request, *, roles: set[str] | None = None) -> AuthenticatedActor: ...
# def _base_ui_context(title: str, actor: AuthenticatedActor) -> dict[str, object]: ...

def create_application(
    config: AppConfig | None = None,
    *,
    clock: Clock | None = None,
    metrics: ServiceMetrics | None = None,
    timer: Timer | None = None,
    templates: Jinja2Templates | None = None,
    # rate_limit_store: KeyValueStore | None = None, # حذف شد
    # idempotency_store: KeyValueStore | None = None, # حذف شد
    readiness_probes: Mapping[str, AsyncProbe] | None = None,
    workflow: ImportToSabtWorkflow | None = None,
    export_runner: ExportJobRunner | None = None,
    export_metrics: ExporterMetrics | None = None,
    export_logger: ExportLogger | None = None,
    # export_signer: SignedURLProvider | None = None, # حذف شد یا تغییر کرد
) -> FastAPI:
    config = config or AppConfig.from_env()
    clock = clock or build_system_clock(config.timezone)
    metrics = metrics or build_metrics(config.observability.metrics_namespace)
    export_metrics = export_metrics or ExporterMetrics(metrics.registry)
    export_logger = export_logger or ExportLogger()
    timer = timer or MonotonicTimer()
    templates = templates or _build_templates()
    # rate_limit_store = rate_limit_store or InMemoryKeyValueStore(...) # حذف شد
    # idempotency_store = idempotency_store or InMemoryKeyValueStore(...) # حذف شد
    readiness_probes = dict(readiness_probes or {})

    configure_logging(config.observability.service_name, config.enable_debug_logs)

    # --- بخش‌های امنیتی حذف شد ---
    # guard = AccessConfigGuard()
    # try: ...
    # except ConfigGuardError: ...
    # tokens: list[TokenDefinition] = ...
    # def _add_token(...): ...
    # service_token = ...
    # env_metrics_token = ...
    # metrics_token_source: str | None = None
    # metrics_token_error: str | None = None
    # metrics_token: str | None = None
    # if env_metrics_token: ...
    # elif access and access.metrics_tokens: ...
    # else: ...
    # if not metrics_token: ...
    # if not tokens: ...
    # jwt_secret = ...
    # token_registry = TokenRegistry(...)
    # signing_keys = ...
    # if not signing_keys: ...
    # signer = DualKeySigner(...)
    # export_signer = export_signer or signer
    # download_secret = ...
    # download_settings = DownloadSettings(...)
    # download_metrics = DownloadMetrics(metrics.registry)
    # security_config = SignatureSecurityConfig()
    # signature_security = SignatureSecurityManager(...)
    # --- پایان بخش‌های امنیتی ---
    # به جای امضای دیجیتال، می‌توان یک امضای ساده یا هیچ امضایی تولید کرد.
    # اما برای سادگی، فرض می‌کنیم export_signer دیگر نیاز نیست.
    # اگر نیاز باشد، باید یک پیاده‌سازی ساده یا mock ایجاد شود.
    # در اینجا فقط export_runner ایجاد می‌شود.

    storage_root = _resolve_storage_root(workflow=workflow)
    storage_root.mkdir(parents=True, exist_ok=True)
    if export_runner is None:
        export_runner = _build_default_export_runner(
            storage_root=storage_root,
            clock=clock,
            metrics=export_metrics,
            logger=export_logger,
        )

    metrics_collector = MetricsCollector(metrics.registry)

    container = ApplicationContainer(
        config=config,
        clock=clock,
        timer=timer,
        metrics=metrics,
        metrics_collector=metrics_collector,
        # download_metrics=download_metrics, # حذف شد
        # download_settings=download_settings, # حذف شد
        # signature_security=signature_security, # حذف شد
        templates=templates,
        # rate_limit_store=rate_limit_store, # حذف شد
        # idempotency_store=idempotency_store, # حذف شد
        readiness_probes=readiness_probes,
        # token_registry=token_registry, # حذف شد
        # download_signer=signer, # حذف شد
        # metrics_token=metrics_token, # حذف شد
        # metrics_token_error=metrics_token_error, # حذف شد
        # metrics_token_source=metrics_token_source, # حذف شد
        storage_root=storage_root,
        export_runner=export_runner,
        export_metrics=export_metrics,
        export_logger=export_logger,
        # export_signer=export_signer, # حذف شد یا تغییر کرد
    )

    # اجازه دسترسی به مستندات عمومی همیشه فعال است
    # public_docs_enabled = _is_truthy(os.getenv("IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS"))
    public_docs_enabled = True # همیشه فعال
    docs_url = "/docs" if public_docs_enabled else None
    redoc_url = "/redoc" if public_docs_enabled else None
    openapi_url = "/openapi.json" if public_docs_enabled else None

    app = FastAPI(
        title="ImportToSabt",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.public_docs_enabled = public_docs_enabled
    static_root = _resolve_static_assets_root()
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=str(static_root)), name="static")
    app.state.diagnostics = {
        "enabled": config.enable_diagnostics,
        "last_chain": [],
        # "last_rate_limit": None, # حذف شد
        # "last_idempotency": None, # حذف شد
        # "last_auth": None, # حذف شد
        # "metrics_token_source": metrics_token_source, # حذف شد
        # "metrics_token_error": metrics_token_error, # حذف شد
    }
    app.state.storage_root = storage_root
    # app.state.download_metrics = download_metrics # حذف شد
    app.state.metrics_collector = metrics_collector
    # app.state.signature_security = signature_security # حذف شد
    # app.state.download_signer = signer # حذف شد
    app.state.service_metrics = metrics

    export_api = ExportAPI(
        runner=export_runner,
        # signer=export_signer, # فرض بر این است که export_api دیگر signer نیاز ندارد یا یک signer ساده دریافت می‌کند
        signer=None, # تغییر داده شد
        metrics=export_metrics,
        logger=export_logger,
        metrics_token=None, # تغییر داده شد
    )
    app.include_router(export_api.create_router(), prefix="/api")
    app.state.export_runner = export_runner
    app.state.export_metrics = export_metrics
    app.state.export_logger = export_logger
    # app.state.export_signer = export_signer # حذف شد
    # app.state.export_rate_limiter = export_api.rate_limiter # حذف شد یا تغییر کرد
    # app.state.rate_limit_snapshot = export_api.snapshot_rate_limit # حذف شد یا تغییر کرد
    # app.state.rate_limit_restore = export_api.restore_rate_limit # حذف شد یا تغییر کرد
    # app.state.rate_limit_configure = export_api.configure_rate_limit # حذف شد یا تغییر کرد
    # app.state.export_readiness_gate = export_api.readiness_gate # احتمالاً هنوز مورد نیاز است

    # endpoint دانلود حذف شد
    # @app.get("/downloads/{token_id}") ...

    # endpointهای UI حذف شدند
    # @app.get("/ui/health", ...) ...
    # @app.get("/ui/exports", ...) ...
    # @app.get("/ui/exports/new", ...) ...
    # @app.get("/ui/jobs/{job_id}", ...) ...
    # @app.get("/ui/uploads", ...) ...

    # endpointهای API که نیازمند احراز هویت بودند حذف یا تغییر کردند
    # @app.get("/api/jobs") ...
    # @app.post("/api/jobs") ...

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
            # بروزرسانی متریک‌ها بدون امنیت
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
            # بروزرسانی متریک‌ها بدون امنیت
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

    # endpoint متریک‌ها بدون نیاز به توکن
    @app.get("/metrics")
    async def metrics_endpoint(request: Request):
        # تمام بررسی‌های احراز هویت حذف شد
        # container.metrics.auth_fail_total.labels(reason="metrics_missing").inc()
        # container.metrics.auth_fail_total.labels(reason="metrics_forbidden").inc()
        # container.metrics.auth_ok_total.labels(role="METRICS_RO").inc()
        # فقط خروجی متریک‌ها
        return PlainTextResponse(render_metrics(container.metrics).decode("utf-8"))

    # endpoint دیاگنوستیک
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
