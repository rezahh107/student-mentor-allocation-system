from __future__ import annotations

import hmac
import os
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from dateutil import parser
from prometheus_client import generate_latest

from .job_runner import ExportJobRunner
from .logging_utils import ExportLogger
from .metrics import ExporterMetrics
from .models import (
    ExportDeltaWindow,
    ExportFilters,
    ExportJobStatus,
    ExportOptions,
    SignedURLProvider,
)


class ExportRequest(BaseModel):
    year: int
    center: int | None = Field(default=None)
    delta_created_at: str | None = None
    delta_id: int | None = None
    chunk_size: int | None = None
    bom: bool | None = None
    excel_mode: bool | None = None


class ExportResponse(BaseModel):
    job_id: str
    status: ExportJobStatus
    middleware_chain: list[str]


class ExportStatusResponse(BaseModel):
    job_id: str
    status: ExportJobStatus
    files: list[dict[str, Any]]
    manifest: dict[str, Any] | None = None


class HMACSignedURLProvider(SignedURLProvider):
    def __init__(self, secret: str, base_url: str = "https://files.local/export") -> None:
        self.secret = secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")

    def sign(self, file_path: str, expires_in: int = 3600) -> str:
        payload = f"{file_path}:{expires_in}"
        digest = hmac.new(self.secret, payload.encode("utf-8"), sha256).hexdigest()
        filename = Path(file_path).name
        return f"{self.base_url}/{filename}?expires={expires_in}&sig={digest}"


def rate_limit_dependency(request: Request) -> None:
    request.state.middleware_chain = ["ratelimit"]


def idempotency_dependency(request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key")) -> str:
    chain = getattr(request.state, "middleware_chain", [])
    chain.append("idempotency")
    request.state.middleware_chain = chain
    return idempotency_key


def auth_dependency(
    request: Request,
    role: str = Header(..., alias="X-Role"),
    center_scope: Optional[int] = Header(default=None, alias="X-Center"),
) -> tuple[str, Optional[int]]:
    chain = getattr(request.state, "middleware_chain", [])
    chain.append("auth")
    request.state.middleware_chain = chain
    if role not in {"ADMIN", "MANAGER"}:
        raise HTTPException(status_code=403, detail="نقش مجاز نیست")
    if role == "MANAGER" and center_scope is None:
        raise HTTPException(status_code=400, detail="کد مرکز الزامی است")
    return role, center_scope


class ExportAPI:
    def __init__(
        self,
        *,
        runner: ExportJobRunner,
        signer: SignedURLProvider,
        metrics: ExporterMetrics,
        logger: ExportLogger,
        metrics_token: str | None = None,
    ) -> None:
        self.runner = runner
        self.signer = signer
        self.metrics = metrics
        self.logger = logger
        self.metrics_token = metrics_token

    def create_router(self) -> APIRouter:
        router = APIRouter()

        @router.post("/exports", response_model=ExportResponse)
        async def create_export(
            payload: ExportRequest,
            request: Request,
            _: None = Depends(rate_limit_dependency),
            idempotency_key: str = Depends(idempotency_dependency),
            auth: tuple[str, Optional[int]] = Depends(auth_dependency),
        ) -> ExportResponse:
            role, center_scope = auth
            if role == "MANAGER" and payload.center != center_scope:
                raise HTTPException(status_code=403, detail="اجازه دسترسی ندارید")
            delta = None
            if payload.delta_created_at and payload.delta_id is not None:
                delta = ExportDeltaWindow(
                    created_at_watermark=parser.isoparse(payload.delta_created_at),
                    id_watermark=payload.delta_id,
                )
            filters = ExportFilters(
                year=payload.year,
                center=payload.center,
                delta=delta,
            )
            options = ExportOptions(
                chunk_size=payload.chunk_size or 50_000,
                include_bom=payload.bom or False,
                excel_mode=payload.excel_mode if payload.excel_mode is not None else True,
            )
            namespace = f"{role}:{center_scope or 'ALL'}:{payload.year}"
            job = self.runner.submit(
                filters=filters,
                options=options,
                idempotency_key=idempotency_key,
                namespace=namespace,
            )
            chain = getattr(request.state, "middleware_chain", [])
            return ExportResponse(job_id=job.id, status=job.status, middleware_chain=chain)

        @router.get("/exports/{job_id}", response_model=ExportStatusResponse)
        async def get_export(job_id: str, request: Request) -> ExportStatusResponse:
            job = self.runner.get_job(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="یافت نشد")
            files = []
            if job.manifest:
                for file in job.manifest.files:
                    signed = self.signer.sign(str(Path(self.runner.exporter.output_dir) / file.name))
                    files.append({"name": file.name, "rows": file.row_count, "url": signed})
                manifest_payload = {
                    "total_rows": job.manifest.total_rows,
                    "generated_at": job.manifest.generated_at.isoformat(),
                }
            else:
                manifest_payload = None
            return ExportStatusResponse(job_id=job.id, status=job.status, files=files, manifest=manifest_payload)

        if self.metrics_token is not None:
            @router.get("/metrics")
            async def metrics_endpoint(token: Optional[str] = Header(default=None, alias="X-Metrics-Token")) -> Response:
                if token != self.metrics_token:
                    raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
                payload = generate_latest(self.metrics.registry)
                return Response(content=payload, media_type="text/plain; version=0.0.4")

        return router


def create_export_api(
    *,
    runner: ExportJobRunner,
    signer: SignedURLProvider,
    metrics: ExporterMetrics,
    logger: ExportLogger,
    metrics_token: str | None = None,
) -> FastAPI:
    api = FastAPI()
    export_api = ExportAPI(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=logger,
        metrics_token=metrics_token,
    )
    api.include_router(export_api.create_router())
    return api
