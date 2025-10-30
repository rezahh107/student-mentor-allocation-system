from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from hashlib import blake2b
from http import HTTPStatus
from pathlib import Path
from typing import Any

from dateutil import parser
from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from sma.phase6_import_to_sabt.clock import Clock, ensure_clock
from sma.phase6_import_to_sabt.errors import (
    EXPORT_IO_FA_MESSAGE,
    EXPORT_VALIDATION_FA_MESSAGE,
)
from sma.phase6_import_to_sabt.job_runner import ExportJobRunner
from sma.phase6_import_to_sabt.logging_utils import ExportLogger
from sma.phase6_import_to_sabt.metrics import ExporterMetrics
from sma.phase6_import_to_sabt.models import (
    ExportDeltaWindow,
    ExportFilters,
    ExportJob,
    ExportJobStatus,
    ExportManifestFile,
    ExportOptions,
    SignedURLProvider,
)
from sma.phase7_release.deploy import ReadinessGate


class ExportRequest(BaseModel):
    year: int
    center: int | None = Field(default=None)
    delta_created_at: str | None = None
    delta_id: int | None = None
    chunk_size: int | None = None
    bom: bool | None = None
    excel_mode: bool | None = None
    format: str | None = Field(default="xlsx")
    idempotency_key: str | None = None


class ExportResponse(BaseModel):
    job_id: str
    status: ExportJobStatus
    format: str


class ExportStatusResponse(BaseModel):
    job_id: str
    status: ExportJobStatus
    files: list[dict[str, Any]]
    manifest: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class SabtExportQuery(BaseModel):
    year: int
    center: int | None = Field(default=None)
    format: str = Field(default="xlsx")
    chunk_size: int | None = None
    bom: bool | None = None
    excel_mode: bool | None = None


class SabtExportResponse(BaseModel):
    job_id: str
    format: str
    files: list[dict[str, Any]]
    manifest: dict[str, Any]


class ExportAPI:
    """Thin wrapper around ``ExportJobRunner`` exposing FastAPI routes."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        runner: ExportJobRunner,
        signer: SignedURLProvider | None,
        metrics: ExporterMetrics,
        logger: ExportLogger,
        readiness_gate: ReadinessGate | None = None,
        redis_probe: Callable[[], Awaitable[bool]] | None = None,
        db_probe: Callable[[], Awaitable[bool]] | None = None,
        duration_clock: Callable[[], float] | None = None,
    ) -> None:
        self.runner = runner
        self.signer = signer or SignedURLProvider()
        self.metrics = metrics
        self.logger = logger
        self.readiness_gate = self._init_readiness_gate(readiness_gate)
        self._redis_probe = redis_probe or self._build_noop_probe()
        self._db_probe = db_probe or self._build_noop_probe()
        self._duration_clock = duration_clock or time.perf_counter
        self._runner_clock = self._resolve_runner_clock(self.runner)

    @staticmethod
    def _resolve_runner_clock(runner: ExportJobRunner) -> Clock:
        clock = getattr(runner, "clock", None)
        return ensure_clock(clock, timezone="Asia/Tehran")

    @staticmethod
    def _build_noop_probe() -> Callable[[], Awaitable[bool]]:
        async def _probe() -> bool:
            return True

        return _probe

    @staticmethod
    def _init_readiness_gate(readiness_gate: ReadinessGate | None) -> ReadinessGate:
        if readiness_gate is not None:
            return readiness_gate
        gate = ReadinessGate(clock=time.monotonic)
        gate.record_cache_warm()
        gate.record_dependency(name="redis", healthy=True)
        gate.record_dependency(name="database", healthy=True)
        return gate

    @staticmethod
    def _validation_error(details: dict[str, Any]) -> HTTPException:
        return HTTPException(
            status_code=400,
            detail={
                "error_code": "EXPORT_VALIDATION_ERROR",
                "message": EXPORT_VALIDATION_FA_MESSAGE,
                "details": details,
            },
        )

    @staticmethod
    def _derive_idempotency_key(request: Request, candidate: str | None) -> str:
        if candidate:
            return candidate
        correlation_id = (
            getattr(request.state, "correlation_id", None)
            or request.headers.get("X-Request-ID")
            or "dev-export"
        )
        digest = blake2b(correlation_id.encode("utf-8"), digest_size=16).hexdigest()
        return f"anon-{digest}"

    def _build_namespace(
        self,
        *,
        year: int,
        center: int | None,
        fmt: str,
        delta: ExportDeltaWindow | None,
    ) -> str:
        parts: list[str] = [str(year), fmt]
        if center is not None:
            parts.insert(0, str(center))
        if delta is not None:
            parts.append(
                f"delta:{delta.created_at_watermark.isoformat()}:{delta.id_watermark}"
            )
        return ":".join(parts)

    def _submit_job(
        self,
        *,
        request: Request,
        payload: ExportRequest,
        delta: ExportDeltaWindow | None,
        options: ExportOptions,
    ) -> ExportJob:
        idempotency_key = self._derive_idempotency_key(request, payload.idempotency_key)
        namespace = self._build_namespace(
            year=payload.year,
            center=payload.center,
            fmt=options.output_format,
            delta=delta,
        )
        correlation_id = getattr(request.state, "correlation_id", uuid.uuid4().hex)
        filters = ExportFilters(year=payload.year, center=payload.center, delta=delta)
        job = self.runner.submit(
            filters=filters,
            options=options,
            idempotency_key=idempotency_key,
            namespace=namespace,
            correlation_id=correlation_id,
        )
        self.metrics.inc_job(job.status.value, options.output_format)
        return job

    def _serialize_files(self, job: ExportJob) -> list[dict[str, Any]]:
        if not job.manifest:
            return []
        files: list[dict[str, Any]] = []
        start = self._duration_clock()
        for file in job.manifest.files:
            artifact = Path(self.runner.exporter.output_dir) / file.name
            url = self.signer.sign(str(artifact))
            sheets = [list(sheet) for sheet in file.sheets] if file.sheets else []
            files.append(
                {
                    "name": file.name,
                    "rows": file.row_count,
                    "sha256": file.sha256,
                    "sheets": sheets,
                    "url": url,
                }
            )
        elapsed = self._duration_clock() - start
        if elapsed >= 0:
            self.metrics.observe_duration("sign_links", elapsed, job.manifest.format)
        return files

    @staticmethod
    def _serialize_manifest(job: ExportJob) -> dict[str, Any] | None:
        if job.manifest is None:
            return None
        manifest = job.manifest
        return {
            "total_rows": manifest.total_rows,
            "generated_at": manifest.generated_at.isoformat(),
            "format": manifest.format,
            "excel_safety": manifest.excel_safety,
            "delta_window": None
            if manifest.delta_window is None
            else {
                "created_at_watermark": (
                    manifest.delta_window.created_at_watermark.isoformat()
                ),
                "id_watermark": manifest.delta_window.id_watermark,
            },
            "files": [
                ExportAPI._serialize_manifest_file(file)
                for file in manifest.files
            ],
        }

    @staticmethod
    def _serialize_manifest_file(file: ExportManifestFile) -> dict[str, Any]:
        sheets = [list(sheet) for sheet in file.sheets] if file.sheets else []
        return {
            "name": file.name,
            "sha256": file.sha256,
            "row_count": file.row_count,
            "sheets": sheets,
        }

    def create_router(self) -> APIRouter:  # noqa: PLR0915
        router = APIRouter()

        @router.post(
            "/exports",
            response_model=ExportResponse,
            status_code=status.HTTP_202_ACCEPTED,
        )
        async def create_export(
            request: Request,
            payload: ExportRequest,
        ) -> ExportResponse:
            delta: ExportDeltaWindow | None = None
            if (payload.delta_created_at is None) ^ (payload.delta_id is None):
                message = "هر دو مقدار پنجره دلتا الزامی است."
                raise self._validation_error({"delta": message})
            if payload.delta_created_at and payload.delta_id is not None:
                delta = ExportDeltaWindow(
                    created_at_watermark=parser.isoparse(payload.delta_created_at),
                    id_watermark=payload.delta_id,
                )
            fmt = (payload.format or "xlsx").lower()
            chunk_size = payload.chunk_size or 50_000
            if chunk_size <= 0:
                message = "اندازهٔ قطعه باید بزرگتر از صفر باشد."
                raise self._validation_error({"chunk_size": message})
            try:
                excel_mode = (
                    True if payload.excel_mode is None else payload.excel_mode
                )
                options = ExportOptions(
                    chunk_size=chunk_size,
                    include_bom=bool(payload.bom),
                    excel_mode=excel_mode,
                    output_format=fmt,
                )
            except ValueError as exc:
                raise self._validation_error({"format": str(exc)}) from exc
            job = self._submit_job(
                request=request,
                payload=payload,
                delta=delta,
                options=options,
            )
            return ExportResponse(
                job_id=job.id,
                status=job.status,
                format=options.output_format,
            )

        @router.get(
            "/exports/{job_id}",
            response_model=ExportStatusResponse,
        )
        async def get_export(job_id: str) -> ExportStatusResponse:
            job = self.runner.get_job(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="EXPORT_NOT_FOUND")
            files = self._serialize_files(job)
            manifest = self._serialize_manifest(job)
            return ExportStatusResponse(
                job_id=job.id,
                status=job.status,
                files=files,
                manifest=manifest,
                error=job.error,
            )

        @router.get(
            "/exports/csv",
            response_model=ExportResponse,
            status_code=status.HTTP_202_ACCEPTED,
            deprecated=True,
        )
        async def legacy_export_csv(
            request: Request,
            year: int,
            center: int | None = None,
        ) -> JSONResponse:
            payload = ExportRequest(year=year, center=center, format="csv")
            options = ExportOptions(
                chunk_size=50_000,
                include_bom=False,
                excel_mode=True,
                output_format="csv",
            )
            job = self._submit_job(
                request=request,
                payload=payload,
                delta=None,
                options=options,
            )
            response_payload = ExportResponse(
                job_id=job.id,
                status=job.status,
                format="csv",
            ).model_dump()
            response = JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=response_payload,
            )
            response.headers["Deprecation"] = "true"
            response.headers["Link"] = (
                "</api/exports?format=csv>; rel=\"successor-version\""
            )
            response.headers["Sunset"] = "2025-03-01T00:00:00Z"
            return response

        @router.get(
            "/export/sabt/v1",
            response_model=SabtExportResponse,
        )
        async def sabt_export(
            request: Request,
            year: int,
            center: int | None = None,
        ) -> SabtExportResponse:
            payload = ExportRequest(year=year, center=center, format="xlsx")
            options = ExportOptions(
                chunk_size=50_000,
                include_bom=False,
                excel_mode=True,
                output_format="xlsx",
            )
            job = self._submit_job(
                request=request,
                payload=payload,
                delta=None,
                options=options,
            )
            self.runner.await_completion(job.id)
            job = self.runner.get_job(job.id)
            if job is None or job.manifest is None:
                raise HTTPException(status_code=500, detail=EXPORT_IO_FA_MESSAGE)
            files = self._serialize_files(job)
            manifest = self._serialize_manifest(job)
            if manifest is None:
                raise HTTPException(status_code=500, detail=EXPORT_IO_FA_MESSAGE)
            return SabtExportResponse(
                job_id=job.id,
                format=options.output_format,
                files=files,
                manifest=manifest,
            )

        @router.get("/healthz")
        async def healthz() -> dict[str, Any]:
            redis_ok = await self._redis_probe()
            db_ok = await self._db_probe()
            fallback_status = HTTPStatus.SERVICE_UNAVAILABLE
            status_code = HTTPStatus.OK if redis_ok and db_ok else fallback_status
            healthy = status_code == HTTPStatus.OK
            if not healthy:
                self.readiness_gate.record_dependency(name="redis", healthy=redis_ok)
                self.readiness_gate.record_dependency(name="database", healthy=db_ok)
            return {
                "status": "ok" if healthy else "degraded",
                "redis": redis_ok,
                "database": db_ok,
            }

        return router


def create_export_api(  # noqa: PLR0913
    *,
    runner: ExportJobRunner,
    signer: SignedURLProvider | None,
    metrics: ExporterMetrics,
    logger: ExportLogger,
    readiness_gate: ReadinessGate | None = None,
    redis_probe: Callable[[], Awaitable[bool]] | None = None,
    db_probe: Callable[[], Awaitable[bool]] | None = None,
    duration_clock: Callable[[], float] | None = None,
) -> FastAPI:
    app = FastAPI()
    export_api = ExportAPI(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=logger,
        readiness_gate=readiness_gate,
        redis_probe=redis_probe,
        db_probe=db_probe,
        duration_clock=duration_clock,
    )
    app.include_router(export_api.create_router())
    app.state.export_metrics = metrics
    app.state.export_readiness_gate = export_api.readiness_gate
    return app


class HMACSignedURLProvider(SignedURLProvider):
    """Compatibility shim maintained for tests and tooling."""

    def __init__(
        self,
        secret: str,
        *,
        base_url: str = "https://files.local/export",
    ) -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._secret = secret

    def sign(self, file_path: str, expires_in: int = 3600) -> str:  # noqa: ARG002
        filename = Path(file_path).name
        return f"{self._base_url}/{filename}?token={self._secret}"


__all__ = [
    "ExportAPI",
    "ExportRequest",
    "ExportResponse",
    "ExportStatusResponse",
    "SabtExportQuery",
    "SabtExportResponse",
    "create_export_api",
    "HMACSignedURLProvider",
]
