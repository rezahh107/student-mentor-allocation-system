from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
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
from sma.phase6_import_to_sabt.xlsx.workflow import ImportToSabtWorkflow

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


def configure_middleware(app: FastAPI, container: ApplicationContainer) -> None:
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

    docs_url = "/docs"
    redoc_url = "/redoc"
    openapi_url = "/openapi.json"

    app = FastAPI(
        title="ImportToSabt",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.public_docs_enabled = True
    static_root = _resolve_static_assets_root()
    if static_root.exists():
        app.mount("/static", StaticFiles(directory=str(static_root)), name="static")
    app.state.diagnostics = {
        "enabled": config.enable_diagnostics,
        "last_chain": [],
    }
    app.state.storage_root = storage_root
    app.state.metrics_collector = metrics_collector
    app.state.service_metrics = metrics

    export_api = ExportAPI(
        runner=export_runner,
        signer=None,
        metrics=export_metrics,
        logger=export_logger,
    )
    app.include_router(export_api.create_router(), prefix="/api")
    app.state.export_runner = export_runner
    app.state.export_metrics = export_metrics
    app.state.export_logger = export_logger
    app.state.export_readiness_gate = export_api.readiness_gate

    install_error_handlers(app)
    configure_middleware(app, container)

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
