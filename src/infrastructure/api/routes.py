# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, Response

from src.application.commands.allocation import GetJobStatus, StartBatchAllocation
from src.interfaces.schemas import AllocationRunRequest, Job, JobStatus
from src.infrastructure.api.error_handlers import install_error_handlers
from src.infrastructure.monitoring.logging import CorrelationIdMiddleware, configure_json_logging
from src.infrastructure.security.auth import require_roles
from src.infrastructure.security.rate_limit import RateLimiter
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest


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
async def run_allocation(req: AllocationRunRequest, user=require_roles("alloc:run")):
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
    app.include_router(router)
    install_error_handlers(app)

    limiter = RateLimiter(limit=100)

    @app.middleware("http")
    async def _rate_limit(request, call_next):  # type: ignore[no-redef]
        key = request.headers.get("X-Api-Key") or request.client.host
        try:
            if not limiter.allow(key):
                return JSONResponse(status_code=429, content={"error": "RATE_LIMIT", "message": "Too Many Requests"})
        except Exception:
            pass  # fail open on limiter errors
        return await call_next(request)

    @app.get("/metrics")
    async def metrics():  # pragma: no cover - integration
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    return app
