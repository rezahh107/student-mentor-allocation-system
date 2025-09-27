from __future__ import annotations

import hmac
import os
import time
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import asyncio
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from dateutil import parser
from prometheus_client import generate_latest

from src.phase7_release.deploy import CircuitBreaker, ReadinessGate, get_debug_context

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


def optional_idempotency_dependency(
    request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> Optional[str]:
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


def optional_auth_dependency(
    request: Request,
    role: str | None = Header(default=None, alias="X-Role"),
    center_scope: Optional[int] = Header(default=None, alias="X-Center"),
) -> tuple[Optional[str], Optional[int]]:
    chain = getattr(request.state, "middleware_chain", [])
    chain.append("auth")
    request.state.middleware_chain = chain
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
        readiness_gate: ReadinessGate | None = None,
        redis_probe: Callable[[], Awaitable[bool]] | None = None,
        db_probe: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.runner = runner
        self.signer = signer
        self.metrics = metrics
        self.logger = logger
        self.metrics_token = metrics_token
        self.readiness_gate = readiness_gate or ReadinessGate(clock=time.monotonic)
        self._redis_probe = redis_probe or self._build_default_redis_probe()
        self._db_probe = db_probe or self._build_default_db_probe()
        self._redis_breaker = CircuitBreaker(clock=time.monotonic, failure_threshold=2, reset_timeout=5.0)
        self._db_breaker = CircuitBreaker(clock=time.monotonic, failure_threshold=2, reset_timeout=5.0)
        self._probe_timeout = 2.5

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
            correlation_id = request.headers.get("X-Request-ID", "-")
            try:
                self.readiness_gate.assert_post_allowed(correlation_id=correlation_id)
            except RuntimeError as exc:
                debug = self._debug_context()
                self.logger.error("POST_GATE_BLOCKED", correlation_id=correlation_id, **debug)
                raise HTTPException(status_code=503, detail={"message": str(exc), "context": debug}) from exc
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

        @router.get("/healthz")
        async def healthz(
            request: Request,
            _: None = Depends(rate_limit_dependency),
            __: Optional[str] = Depends(optional_idempotency_dependency),
            ___: tuple[Optional[str], Optional[int]] = Depends(optional_auth_dependency),
        ) -> dict[str, Any]:
            healthy, probes = await self._execute_probes()
            if not healthy:
                raise HTTPException(status_code=503, detail={"message": "وضعیت سامانه ناسالم است", "context": self._debug_context()})
            chain = getattr(request.state, "middleware_chain", [])
            return {"status": "ok", "probes": probes, "middleware_chain": chain}

        @router.get("/readyz")
        async def readyz(
            request: Request,
            _: None = Depends(rate_limit_dependency),
            __: Optional[str] = Depends(optional_idempotency_dependency),
            ___: tuple[Optional[str], Optional[int]] = Depends(optional_auth_dependency),
        ) -> dict[str, Any]:
            healthy, probes = await self._execute_probes()
            chain = getattr(request.state, "middleware_chain", [])
            if not self.readiness_gate.ready():
                raise HTTPException(status_code=503, detail={"message": "سامانه در حال آماده‌سازی است", "context": self._debug_context()})
            return {"status": "ready", "probes": probes, "middleware_chain": chain}

        if self.metrics_token is not None:
            @router.get("/metrics")
            async def metrics_endpoint(token: Optional[str] = Header(default=None, alias="X-Metrics-Token")) -> Response:
                if token != self.metrics_token:
                    raise HTTPException(status_code=403, detail="دسترسی غیرمجاز")
                payload = generate_latest(self.metrics.registry)
                return Response(content=payload, media_type="text/plain; version=0.0.4")

        return router

    async def _execute_probes(self) -> tuple[bool, dict[str, bool]]:
        redis_ok = await self._check_dependency("redis", self._redis_probe, self._redis_breaker)
        db_ok = await self._check_dependency("database", self._db_probe, self._db_breaker)
        return redis_ok and db_ok, {"redis": redis_ok, "database": db_ok}

    async def _check_dependency(
        self,
        name: str,
        probe: Callable[[], Awaitable[bool]],
        breaker: CircuitBreaker,
    ) -> bool:
        if not breaker.allow():
            self.readiness_gate.record_dependency(name=name, healthy=False, error="circuit-open")
            return False
        try:
            result = await asyncio.wait_for(probe(), timeout=self._probe_timeout)
        except asyncio.TimeoutError:
            breaker.record_failure()
            self.readiness_gate.record_dependency(name=name, healthy=False, error="timeout")
            return False
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure()
            self.readiness_gate.record_dependency(name=name, healthy=False, error=type(exc).__name__)
            return False
        if result:
            breaker.record_success()
            self.readiness_gate.record_dependency(name=name, healthy=True)
            return True
        breaker.record_failure()
        self.readiness_gate.record_dependency(name=name, healthy=False, error="probe-failed")
        return False

    def _debug_context(self) -> dict[str, object]:
        redis_client = getattr(self.runner, "redis", None)

        def _redis_keys() -> list[str]:
            if redis_client is None:
                return []
            try:
                return [str(key) for key in sorted(redis_client.keys("*"))]
            except Exception:  # noqa: BLE001
                return []

        return get_debug_context(
            redis_keys=_redis_keys,
            rate_limit_state=getattr(self.runner, "rate_limit_state", lambda: {"mode": "offline"}),
            middleware_chain=lambda: ["ratelimit", "idempotency", "auth"],
            clock=time.monotonic,
        )

    def _build_default_redis_probe(self) -> Callable[[], Awaitable[bool]]:
        async def _probe() -> bool:
            key = "phase7:probe"

            def _call() -> bool:
                self.runner.redis.setnx(key, "1", ex=5)
                self.runner.redis.delete(key)
                return True

            try:
                return await asyncio.to_thread(_call)
            except Exception:  # noqa: BLE001
                return False

        return _probe

    def _build_default_db_probe(self) -> Callable[[], Awaitable[bool]]:
        async def _probe() -> bool:
            return True

        return _probe


def create_export_api(
    *,
    runner: ExportJobRunner,
    signer: SignedURLProvider,
    metrics: ExporterMetrics,
    logger: ExportLogger,
    metrics_token: str | None = None,
    readiness_gate: ReadinessGate | None = None,
    redis_probe: Callable[[], Awaitable[bool]] | None = None,
    db_probe: Callable[[], Awaitable[bool]] | None = None,
) -> FastAPI:
    api = FastAPI()
    export_api = ExportAPI(
        runner=runner,
        signer=signer,
        metrics=metrics,
        logger=logger,
        metrics_token=metrics_token,
        readiness_gate=readiness_gate,
        redis_probe=redis_probe,
        db_probe=db_probe,
    )
    api.include_router(export_api.create_router())
    return api
