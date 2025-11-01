from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

from sma.phase6_import_to_sabt.api import ExportAPI
from sma.phase6_import_to_sabt.app.clock import Clock, build_system_clock
from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.app.errors import install_error_handlers
from sma.phase6_import_to_sabt.app.logging_config import configure_logging
from sma.phase6_import_to_sabt.app.middleware import (
    CorrelationIdMiddleware,
    MetricsMiddleware,
    RequestLoggingMiddleware,
)
from sma.phase6_import_to_sabt.app.probes import AsyncProbe, ProbeResult
from sma.phase6_import_to_sabt.app.timing import MonotonicTimer, Timer
from sma.phase6_import_to_sabt.app.utils import normalize_token
from sma.phase6_import_to_sabt.data_source import InMemoryDataSource
from sma.phase6_import_to_sabt.exporter import ImportToSabtExporter
from sma.phase6_import_to_sabt.job_runner import ExportJobRunner
from sma.phase6_import_to_sabt.logging_utils import ExportLogger
from sma.phase6_import_to_sabt.metrics import ExporterMetrics
from sma.phase6_import_to_sabt.obs.metrics import (
    ServiceMetrics,
    build_metrics,
    render_metrics,
)
from sma.phase6_import_to_sabt.observability import MetricsCollector
from sma.phase6_import_to_sabt.roster import InMemoryRoster
from sma.phase6_import_to_sabt.xlsx.metrics import build_import_export_metrics
from sma.phase6_import_to_sabt.xlsx.router import build_router as create_xlsx_router
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow
from sma.phase6_import_to_sabt.models import ExportFilters, ExportSnapshot
from sma.phase6_import_to_sabt.app.security import (
    AuthMiddleware,
    IdempotencyMiddleware,
    RateLimitMiddleware,
)
from sma.phase6_import_to_sabt.app.stores import InMemoryKeyValueStore, KeyValueStore
from sma.phase6_import_to_sabt.models import SignedURLProvider

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplicationContainer:
    config: AppConfig
    clock: Clock
    timer: Timer
    metrics: ServiceMetrics
    metrics_collector: MetricsCollector
    templates: Jinja2Templates
    readiness_probes: Mapping[str, AsyncProbe]
    storage_root: Path
    export_runner: ExportJobRunner
    export_metrics: ExporterMetrics
    export_logger: ExportLogger


async def _run_probe(name: str, probe: AsyncProbe, timeout: float) -> ProbeResult:
    result = await probe(timeout)
    logger.debug(
        "probe.result",
        extra={"correlation_id": None, "component": name, "outcome": result.healthy},
    )
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
    normalized = normalize_token(str(value))
    return normalized or ""


def _resolve_storage_root(*, workflow: ImportToSabtWorkflow | None) -> Path:
    if workflow is not None:
        return Path(workflow.storage_dir).resolve()

    env_mapping = dict(os.environ)
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
    roster = InMemoryRoster({})
    exporter = ImportToSabtExporter(
        data_source=data_source,
        roster=roster,
        output_dir=exports_root,
        metrics=metrics,
        clock=clock,
    )
    return ExportJobRunner(
        exporter=exporter,
        metrics=metrics,
        logger=logger,
        clock=clock,
    )


def _build_default_data_provider(
    *,
    export_runner: ExportJobRunner,
    clock: Clock,
) -> Callable[[int, int | None], list[dict[str, object]]]:
    exporter = getattr(export_runner, "exporter", None)
    if exporter is None:
        return lambda year, center: []
    data_source = getattr(exporter, "data_source", None)
    if data_source is None:
        return lambda year, center: []

    def _provide(year: int, center: int | None) -> list[dict[str, object]]:
        filters = ExportFilters(year=year, center=center)
        snapshot = ExportSnapshot(marker=f"xlsx:{year}:{center or 'all'}", created_at=clock.now())
        rows = data_source.fetch_rows(filters, snapshot)
        return [asdict(row) for row in rows]

    return _provide


def _build_default_workflow(
    *,
    storage_root: Path,
    clock: Clock,
    export_runner: ExportJobRunner,
) -> ImportToSabtWorkflow:
    workflow_metrics = build_import_export_metrics()
    workflow_storage = storage_root / "xlsx"
    workflow_storage.mkdir(parents=True, exist_ok=True)
    data_provider = _build_default_data_provider(export_runner=export_runner, clock=clock)
    return ImportToSabtWorkflow(
        storage_dir=workflow_storage,
        clock=clock,
        metrics=workflow_metrics,
        data_provider=data_provider,
    )


def configure_middleware(
    app: FastAPI,
    container: ApplicationContainer,
    *,
    rate_limit_store: KeyValueStore,
    idempotency_store: KeyValueStore,
) -> None:
    app.add_middleware(CorrelationIdMiddleware, clock=container.clock)
    app.add_middleware(
        MetricsMiddleware,
        metrics=container.metrics,
        timer=container.timer,
    )
    app.add_middleware(
        RequestLoggingMiddleware,
        diagnostics=lambda: getattr(app.state, "diagnostics", None),
    )
    app.add_middleware(
        RateLimitMiddleware,
        store=rate_limit_store,
        config=container.config.ratelimit,
        clock=container.clock,
    )
    app.add_middleware(
        IdempotencyMiddleware,
        store=idempotency_store,
    )
    app.add_middleware(
        AuthMiddleware,
        config=container.config.auth,
    )


def create_application(  # noqa: PLR0913, PLR0915
    config: AppConfig | None = None,
    *,
    clock: Clock | None = None,
    metrics: ServiceMetrics | None = None,
    timer: Timer | None = None,
    templates: Jinja2Templates | None = None,
    readiness_probes: Mapping[str, AsyncProbe] | None = None,
    workflow: ImportToSabtWorkflow | None = None,
    export_runner: ExportJobRunner | None = None,
    export_metrics: ExporterMetrics | None = None,
    export_logger: ExportLogger | None = None,
    rate_limit_store: KeyValueStore | None = None,
    idempotency_store: KeyValueStore | None = None,
    export_signer: SignedURLProvider | None = None,
) -> FastAPI:
    config = config or AppConfig.from_env()
    clock = clock or build_system_clock(config.timezone)
    metrics = metrics or build_metrics(config.observability.metrics_namespace)
    export_metrics = export_metrics or ExporterMetrics(metrics.registry)
    export_logger = export_logger or ExportLogger()
    timer = timer or MonotonicTimer()
    templates = templates or _build_templates()
    readiness_probes = dict(readiness_probes or {})

    configure_logging(config.observability.service_name, config.enable_debug_logs)

    storage_root = _resolve_storage_root(workflow=workflow)
    storage_root.mkdir(parents=True, exist_ok=True)
    if export_runner is None:
        export_runner = _build_default_export_runner(
            storage_root=storage_root,
            clock=clock,
            metrics=export_metrics,
            logger=export_logger,
        )

    if workflow is None:
        workflow = _build_default_workflow(
            storage_root=storage_root,
            clock=clock,
            export_runner=export_runner,
        )

    metrics_collector = MetricsCollector(metrics.registry)

    container = ApplicationContainer(
        config=config,
        clock=clock,
        timer=timer,
        metrics=metrics,
        metrics_collector=metrics_collector,
        templates=templates,
        readiness_probes=readiness_probes,
        storage_root=storage_root,
        export_runner=export_runner,
        export_metrics=export_metrics,
        export_logger=export_logger,
    )

    docs_enabled = os.getenv("IMPORT_TO_SABT_SECURITY__PUBLIC_DOCS", "").lower() in {
        "1",
        "true",
        "yes",
    }
    docs_url = "/docs" if docs_enabled else None
    redoc_url = "/redoc" if docs_enabled else None
    openapi_url = "/openapi.json" if docs_enabled else None

    rate_limit_store = rate_limit_store or InMemoryKeyValueStore(
        namespace=f"{config.ratelimit.namespace}:ratelimit",
        clock=clock,
    )
    idempotency_store = idempotency_store or InMemoryKeyValueStore(
        namespace=f"{config.ratelimit.namespace}:idempotency",
        clock=clock,
    )

    app = FastAPI(
        title="ImportToSabt",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.public_docs_enabled = docs_enabled
    static_root = _resolve_static_assets_root()
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=str(static_root)), name="static")
    app.state.diagnostics = {
        "enabled": config.enable_diagnostics,
        "last_chain": [],
        "last_rate_limit": None,
        "last_idempotency": None,
        "last_auth": None,
    }
    app.state.storage_root = storage_root
    app.state.metrics_collector = metrics_collector
    app.state.service_metrics = metrics
    app.state.rate_limit_store = rate_limit_store
    app.state.idempotency_store = idempotency_store

    export_api = ExportAPI(
        runner=export_runner,
        signer=export_signer,
        metrics=export_metrics,
        logger=export_logger,
    )
    app.include_router(export_api.create_router(), prefix="/api")
    xlsx_router = create_xlsx_router(workflow)
    app.include_router(xlsx_router, prefix="/api/xlsx")
    app.state.export_runner = export_runner
    app.state.export_metrics = export_metrics
    app.state.export_logger = export_logger
    app.state.export_readiness_gate = export_api.readiness_gate
    app.state.xlsx_workflow = workflow

    install_error_handlers(app)
    configure_middleware(
        app,
        container,
        rate_limit_store=rate_limit_store,
        idempotency_store=idempotency_store,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        results = []
        for name, probe in container.readiness_probes.items():
            timeout = container.config.health_timeout_seconds
            result = await _run_probe(name, probe, timeout)
            container.metrics.readiness_total.labels(
                component=name, status="healthy" if result.healthy else "degraded"
            ).inc()
            results.append(result)
        return {
            "status": "ok",
            "checked_at": container.clock.now().isoformat(),
            "components": [result.__dict__ for result in results],
        }

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        results = []
        ready = True
        for name, probe in container.readiness_probes.items():
            timeout = container.config.readiness_timeout_seconds
            result = await _run_probe(name, probe, timeout)
            container.metrics.readiness_total.labels(
                component=name, status="ready" if result.healthy else "error"
            ).inc()
            results.append(result)
            ready &= result.healthy
        status_code = 200 if ready else 503
        payload = {
            "status": "ready" if ready else "not_ready",
            "checked_at": container.clock.now().isoformat(),
            "components": [result.__dict__ for result in results],
        }
        return JSONResponse(status_code=status_code, content=payload)

    metrics_enabled = os.getenv("METRICS_ENDPOINT_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }
    app.state.metrics_endpoint_enabled = metrics_enabled

    if metrics_enabled:

        @app.get("/metrics")
        async def metrics_endpoint() -> PlainTextResponse:
            return PlainTextResponse(render_metrics(container.metrics).decode("utf-8"))

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
