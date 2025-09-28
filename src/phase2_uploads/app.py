from __future__ import annotations

import io
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest
from redis import Redis

from .clock import Clock, SystemClock
from .config import DEFAULT_CONFIG, UploadsConfig
from .errors import UploadError, envelope
from .metrics import UploadsMetrics
from .middleware import AuthMiddleware, IdempotencyMiddleware, RateLimitMiddleware
from .repository import UploadRepository, create_sqlite_repository
from .service import UploadContext, UploadService
from .storage import AtomicStorage
from .validator import CSVValidator


def _ensure_templates() -> Jinja2Templates:
    base = Path(__file__).resolve().parent.parent / "ui" / "templates"
    return Jinja2Templates(directory=str(base))


def create_app(
    *,
    config: UploadsConfig = DEFAULT_CONFIG,
    repository: Optional[UploadRepository] = None,
    redis_client: Optional[Redis] = None,
    clock: Optional[Clock] = None,
    registry: Optional[CollectorRegistry] = None,
) -> FastAPI:
    config.ensure_directories()
    repository = repository or create_sqlite_repository()
    if redis_client is None:
        try:
            redis_client = Redis(host="localhost", port=6379, decode_responses=False)
            redis_client.ping()
        except Exception:  # pragma: no cover - fallback for tests
            from fakeredis import FakeStrictRedis

            redis_client = FakeStrictRedis()
    clock = clock or SystemClock()
    registry = registry or CollectorRegistry()
    metrics = UploadsMetrics(registry)
    storage = AtomicStorage(config.storage_dir)
    validator = CSVValidator(preview_rows=config.ui_preview_rows)
    service = UploadService(
        config=config,
        repository=repository,
        storage=storage,
        validator=validator,
        redis_client=redis_client,
        metrics=metrics,
        clock=clock,
    )

    app = FastAPI()
    app.state.upload_service = service
    app.state.registry = registry
    app.state.config = config
    app.state.templates = _ensure_templates()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware, redis=redis_client)

    @app.exception_handler(UploadError)
    async def upload_error_handler(request: Request, exc: UploadError):
        return JSONResponse(exc.envelope.to_dict(), status_code=400)

    def get_service() -> UploadService:
        return app.state.upload_service

    def _parse_multipart(content_type: str | None, body: bytes):
        def _multipart_error(reason: str) -> UploadError:
            return UploadError(
                envelope(
                    "UPLOAD_MULTIPART_INVALID",
                    details={"reason": reason},
                )
            )

        if not content_type:
            raise _multipart_error("missing-content-type")
        if "boundary=" not in content_type:
            raise _multipart_error("missing-boundary")
        boundary = content_type.split("boundary=")[-1].strip()
        if not boundary:
            raise _multipart_error("empty-boundary")
        delimiter = f"--{boundary}".encode("utf-8")
        if delimiter not in body:
            raise _multipart_error("boundary-not-found")
        if not body.strip().endswith(delimiter + b"--") and not body.strip().endswith(
            delimiter + b"--\r\n"
        ):
            raise _multipart_error("missing-closing-boundary")

        fields: dict[str, str] = {}
        file_payload: bytes | None = None
        filename = "upload.csv"
        file_parts = 0
        parts = body.split(delimiter)
        for raw_part in parts:
            if not raw_part or raw_part in (b"", b"--"):
                continue
            part = raw_part.lstrip(b"\r\n")
            if part in (b"", b"--", b"--\r\n"):
                continue
            if b"\r\n\r\n" not in part:
                raise _multipart_error("header-terminator-missing")
            header, _, value = part.partition(b"\r\n\r\n")
            headers = header.decode("utf-8", errors="ignore").split("\r\n")
            disposition_line = next(
                (h for h in headers if h.lower().startswith("content-disposition")),
                "",
            )
            if not disposition_line:
                raise _multipart_error("disposition-missing")
            attrs: dict[str, str] = {}
            for item in disposition_line.split(";"):
                if "=" not in item:
                    continue
                key, val = item.strip().split("=", 1)
                attrs[key.lower()] = val.strip().strip('"')
            name = attrs.get("name")
            if not name:
                raise _multipart_error("name-missing")
            if value.endswith(b"\r\n"):
                payload = value[:-2]
            else:
                payload = value
            if attrs.get("filename") is not None:
                file_parts += 1
                if file_parts > 1:
                    raise UploadError(envelope("UPLOAD_MULTIPART_FILE_COUNT"))
                filename = attrs.get("filename") or filename
                if not payload:
                    raise _multipart_error("file-empty")
                file_payload = payload
            else:
                try:
                    fields[name] = payload.decode("utf-8").strip()
                except UnicodeDecodeError as exc:  # pragma: no cover - strict decode
                    raise _multipart_error("field-decode-error") from exc
        if file_payload is None:
            raise _multipart_error("file-missing")
        return fields, filename, file_payload

    @app.post("/uploads")
    async def post_upload(
        request: Request,
        service: UploadService = Depends(get_service),
    ):
        fields, filename, file_bytes = _parse_multipart(
            request.headers.get("content-type"), await request.body()
        )
        profile = fields.get("profile")
        year = fields.get("year")
        if not profile or profile not in service.config.allowed_profiles:
            raise HTTPException(status_code=400, detail="profile-not-allowed")
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="year-invalid")
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="idempotency-missing")
        rid = request.headers.get("X-Request-ID", uuid4().hex)
        namespace = request.headers.get("X-Namespace", service.config.namespace)
        context = UploadContext(
            profile=profile,
            year=year_int,
            filename=filename,
            rid=rid,
            namespace=namespace,
            idempotency_key=idempotency_key,
        )
        record = service.upload(context, io.BytesIO(file_bytes))
        manifest = record.manifest() or {}
        response = {"id": record.id, "manifest": manifest, "status": record.status}
        if request.headers.get("X-Debug-Middleware") == "1":
            response["middleware_chain"] = getattr(request.state, "middleware_chain", [])
        return response

    @app.get("/uploads/{upload_id}")
    async def get_upload(upload_id: str, service: UploadService = Depends(get_service)):
        record = service.get_upload(upload_id)
        return {"id": record.id, "status": record.status, "manifest": record.manifest()}

    @app.post("/uploads/{upload_id}/activate")
    async def activate_upload(
        request: Request,
        upload_id: str,
        service: UploadService = Depends(get_service),
    ):
        rid = request.headers.get("X-Request-ID", uuid4().hex)
        namespace = request.headers.get("X-Namespace", service.config.namespace)
        record = service.activate(upload_id, rid=rid, namespace=namespace)
        return {"id": record.id, "status": record.status}

    @app.get("/metrics")
    async def metrics_endpoint(request: Request):
        token = request.query_params.get("token")
        if token != config.metrics_token:
            raise HTTPException(status_code=401, detail="unauthorized")
        data = generate_latest(app.state.registry)
        return PlainTextResponse(data.decode("utf-8"), media_type=CONTENT_TYPE_LATEST)

    @app.get("/uploads", response_class=HTMLResponse)
    async def uploads_page(request: Request):
        return app.state.templates.TemplateResponse(
            request,
            "uploads/index.html",
            {
                "request": request,
                "messages": [],
                "preview_rows": [],
            },
        )

    return app
