from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Iterable
from uuid import uuid4
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from mimetypes import guess_type
from prometheus_client import CollectorRegistry, Counter, Histogram

from phase6_import_to_sabt.clock import Clock, ensure_clock


logger = logging.getLogger(__name__)

_CHUNK_SIZE = 64 * 1024
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY = 0.01


class DownloadError(Exception):
    """Domain specific download error with deterministic Persian message."""

    def __init__(self, message: str, *, status_code: int, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class DownloadTokenPayload:
    namespace: str
    filename: str
    sha256: str
    size: int
    exp: int
    version: str | None = None
    created_at: str | None = None

    @staticmethod
    def from_mapping(mapping: dict[str, object]) -> "DownloadTokenPayload":
        try:
            namespace = str(mapping["namespace"])
            filename = str(mapping["filename"])
            sha256 = str(mapping["sha256"])
            size = int(mapping["size"])
            exp = int(mapping["exp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DownloadError(
                "توکن دانلود نامعتبر یا منقضی است.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="DOWNLOAD_INVALID_TOKEN",
            ) from exc
        version = mapping.get("version")
        created_at = mapping.get("created_at")
        return DownloadTokenPayload(
            namespace=namespace,
            filename=filename,
            sha256=sha256,
            size=size,
            exp=exp,
            version=None if version in {None, ""} else str(version),
            created_at=None if created_at in {None, ""} else str(created_at),
        )


@dataclass(slots=True)
class DownloadRetryPolicy:
    attempts: int = _DEFAULT_MAX_ATTEMPTS
    base_delay: float = _DEFAULT_BASE_DELAY


class DownloadMetrics:
    """Prometheus metrics for the download gateway."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.requests_total = Counter(
            "download_requests_total",
            "Total download requests by outcome",
            labelnames=("status",),
            registry=self.registry,
        )
        self.bytes_total = Counter(
            "download_bytes_total",
            "Total bytes streamed to clients",
            registry=self.registry,
        )
        self.bytes_histogram = Histogram(
            "download_response_bytes",
            "Histogram of bytes sent per response",
            registry=self.registry,
            buckets=(512, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, float("inf")),
        )
        self.range_requests_total = Counter(
            "download_range_requests_total",
            "Download range requests by outcome",
            labelnames=("status",),
            registry=self.registry,
        )
        self.invalid_token_total = Counter(
            "download_invalid_token_total",
            "Total invalid or expired download tokens",
            registry=self.registry,
        )
        self.not_found_total = Counter(
            "download_not_found_total",
            "Total missing download artifacts",
            registry=self.registry,
        )
        self.retry_total = Counter(
            "download_retry_total",
            "Retry attempts for download streaming",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self.retry_exhaustion_total = Counter(
            "download_exhaustion_total",
            "Retry exhaustion occurrences for downloads",
            registry=self.registry,
        )

    def observe_bytes(self, length: int) -> None:
        self.bytes_total.inc(length)
        self.bytes_histogram.observe(length)


@dataclass(slots=True)
class DownloadSettings:
    workspace_root: Path
    secret: bytes
    retry: DownloadRetryPolicy
    chunk_size: int = _CHUNK_SIZE


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def encode_download_token(payload: DownloadTokenPayload, *, secret: bytes) -> str:
    raw = json.dumps(
        {
            "namespace": payload.namespace,
            "filename": payload.filename,
            "sha256": payload.sha256,
            "size": payload.size,
            "exp": payload.exp,
            "version": payload.version,
            "created_at": payload.created_at,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return f"{_base64url_encode(raw)}.{_base64url_encode(signature)}"


def decode_download_token(token: str, *, secret: bytes, clock: Clock) -> DownloadTokenPayload:
    if not token:
        raise DownloadError(
            "توکن دانلود نامعتبر یا منقضی است.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="DOWNLOAD_INVALID_TOKEN",
        )
    parts = token.split(".")
    if len(parts) != 2:
        raise DownloadError(
            "توکن دانلود نامعتبر یا منقضی است.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="DOWNLOAD_INVALID_TOKEN",
        )
    payload_part, signature_part = parts
    try:
        payload_bytes = _base64url_decode(payload_part)
        signature_bytes = _base64url_decode(signature_part)
    except (ValueError, binascii.Error) as exc:
        raise DownloadError(
            "توکن دانلود نامعتبر یا منقضی است.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="DOWNLOAD_INVALID_TOKEN",
        ) from exc
    expected_signature = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_signature, signature_bytes):
        raise DownloadError(
            "توکن دانلود نامعتبر یا منقضی است.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="DOWNLOAD_INVALID_TOKEN",
        )
    try:
        payload_mapping = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise DownloadError(
            "توکن دانلود نامعتبر یا منقضی است.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="DOWNLOAD_INVALID_TOKEN",
        ) from exc
    payload = DownloadTokenPayload.from_mapping(payload_mapping)
    now_ts = int(clock.now().timestamp())
    if payload.exp <= now_ts:
        raise DownloadError(
            "توکن دانلود نامعتبر یا منقضی است.",
            status_code=status.HTTP_403_FORBIDDEN,
            code="DOWNLOAD_INVALID_TOKEN",
        )
    return payload


@dataclass(slots=True)
class DownloadContext:
    correlation_id: str
    namespace: str
    filename: str
    sha_prefix: str
    range_start: int | None
    range_end: int | None
    artifact_size: int | None

    def as_log(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "correlation_id": self.correlation_id,
            "namespace": self.namespace,
            "artifact_filename": self.filename,
            "sha256_prefix": self.sha_prefix,
        }
        if self.artifact_size is not None:
            payload["artifact_size"] = self.artifact_size
        if self.range_start is not None or self.range_end is not None:
            payload["range"] = {"start": self.range_start, "end": self.range_end}
        return payload


class DownloadGateway:
    """Serve finalized export artifacts with deterministic guarantees."""

    def __init__(
        self,
        *,
        settings: DownloadSettings,
        clock: Clock,
        metrics: DownloadMetrics,
        retryable: tuple[type[Exception], ...] = (OSError,),
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = DownloadSettings(
            workspace_root=settings.workspace_root.resolve(),
            secret=settings.secret,
            retry=settings.retry,
            chunk_size=settings.chunk_size,
        )
        self._clock = ensure_clock(clock, timezone="Asia/Tehran")
        self._metrics = metrics
        self._retryable = retryable
        self._sleep = sleeper or (lambda duration: asyncio.sleep(duration))

    async def handle(self, request: Request, token: str) -> Response:
        correlation_id = request.headers.get("X-Request-ID") or getattr(
            request.state, "correlation_id", str(uuid4())
        )
        try:
            payload = decode_download_token(token, secret=self._settings.secret, clock=self._clock)
        except DownloadError as exc:
            self._metrics.requests_total.labels(status="invalid_token").inc()
            self._metrics.invalid_token_total.inc()
            logger.warning(
                "download.token_invalid",
                extra={"correlation_id": correlation_id, "reason": exc.code},
            )
            return self._error_response(exc)
        context = DownloadContext(
            correlation_id=correlation_id,
            namespace=payload.namespace,
            filename=payload.filename,
            sha_prefix=payload.sha256[:12],
            range_start=None,
            range_end=None,
            artifact_size=None,
        )
        try:
            return await self._serve(request, payload, context)
        except DownloadError as exc:
            status_label = self._status_label(exc.code)
            self._metrics.requests_total.labels(status=status_label).inc()
            if exc.code == "DOWNLOAD_NOT_FOUND":
                self._metrics.not_found_total.inc()
            logger.warning("download.failure", extra={"event": exc.code, **context.as_log()})
            return self._error_response(exc)

    async def _serve(
        self,
        request: Request,
        payload: DownloadTokenPayload,
        context: DownloadContext,
    ) -> Response:
        namespace = self._sanitize_segment(payload.namespace)
        filename = self._sanitize_segment(payload.filename)
        workspace_value = getattr(request.app.state, "storage_root", None)
        if workspace_value is None:
            workspace_root = self._settings.workspace_root
        else:
            workspace_root = Path(workspace_value)
        workspace_root = workspace_root.resolve()
        if not workspace_root.exists():
            raise DownloadError(
                "سرویس دانلود در دسترس نیست.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="DOWNLOAD_UNAVAILABLE",
            )
        namespace_dir = (workspace_root / namespace).resolve()
        if not namespace_dir.is_dir() or not namespace_dir.is_relative_to(workspace_root):
            raise DownloadError(
                "شیء درخواستی یافت نشد.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="DOWNLOAD_NOT_FOUND",
            )
        if any(namespace_dir.glob("*.part")):
            raise DownloadError(
                "فایل در حال نهایی‌سازی است؛ بعداً تلاش کنید.",
                status_code=status.HTTP_409_CONFLICT,
                code="DOWNLOAD_IN_PROGRESS",
            )
        manifest_path = namespace_dir / "export_manifest.json"
        if not manifest_path.is_file():
            raise DownloadError(
                "شیء درخواستی یافت نشد.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="DOWNLOAD_NOT_FOUND",
            )
        manifest = self._load_manifest(manifest_path)
        manifest_entry = self._find_manifest_entry(manifest, filename)
        if manifest_entry is None:
            raise DownloadError(
                "شیء درخواستی یافت نشد.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="DOWNLOAD_NOT_FOUND",
            )
        expected_sha = manifest_entry.get("sha256")
        expected_size = int(manifest_entry.get("byte_size", payload.size))
        if expected_sha != payload.sha256 or expected_size != payload.size:
            raise DownloadError(
                "شیء درخواستی یافت نشد.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="DOWNLOAD_NOT_FOUND",
            )
        target = (namespace_dir / filename).resolve()
        if not target.is_file() or not target.is_relative_to(namespace_dir):
            raise DownloadError(
                "شیء درخواستی یافت نشد.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="DOWNLOAD_NOT_FOUND",
            )
        actual_size = target.stat().st_size
        if actual_size != expected_size:
            raise DownloadError(
                "شیء درخواستی یافت نشد.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="DOWNLOAD_NOT_FOUND",
            )
        context.artifact_size = actual_size
        etag_value = expected_sha.lower()
        if self._if_none_match(request.headers.get("if-none-match"), etag_value):
            self._metrics.requests_total.labels(status="not_modified").inc()
            response = Response(status_code=status.HTTP_304_NOT_MODIFIED)
            response.headers["ETag"] = f'"{etag_value}"'
            response.headers["X-Request-ID"] = context.correlation_id
            return response
        range_header = request.headers.get("range")
        range_slice: tuple[int, int] | None = None
        if range_header:
            try:
                range_slice = self._parse_range(range_header, actual_size)
            except DownloadError:
                self._metrics.range_requests_total.labels(status="rejected").inc()
                raise
            else:
                self._metrics.range_requests_total.labels(status="accepted").inc()
        else:
            self._metrics.range_requests_total.labels(status="absent").inc()
        file_handle = await self._open_with_retry(target)
        if actual_size == 0:
            start, end = 0, -1
        elif range_slice:
            start, end = range_slice
        else:
            start, end = 0, actual_size - 1
        context.range_start = start if range_slice else None
        context.range_end = end if range_slice else None
        stream = self._iter_file(file_handle, start=start, end=end)
        length = max(end - start + 1, 0)
        headers = {
            "Content-Disposition": self._content_disposition(filename),
            "Content-Type": self._guess_mime(filename),
            "Accept-Ranges": "bytes",
            "ETag": f'"{etag_value}"',
            "X-Request-ID": context.correlation_id,
        }
        if range_slice:
            headers["Content-Range"] = f"bytes {start}-{end}/{actual_size}"
            status_code = status.HTTP_206_PARTIAL_CONTENT
            self._metrics.requests_total.labels(status="partial").inc()
        else:
            status_code = status.HTTP_200_OK
            self._metrics.requests_total.labels(status="success").inc()
        headers["Content-Length"] = str(length)
        response = StreamingResponse(stream, media_type=headers["Content-Type"], status_code=status_code, headers=headers)
        self._metrics.observe_bytes(length)
        logger.info("download.served", extra={"event": "DOWNLOAD_OK", **context.as_log(), "bytes": length})
        return response

    def _sanitize_segment(self, value: str) -> str:
        candidate = value.strip()
        if not candidate:
            raise DownloadError(
                "توکن دانلود نامعتبر یا منقضی است.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="DOWNLOAD_INVALID_TOKEN",
            )
        parts = Path(candidate).parts
        if len(parts) != 1 or parts[0] in {"..", "."}:
            raise DownloadError(
                "توکن دانلود نامعتبر یا منقضی است.",
                status_code=status.HTTP_403_FORBIDDEN,
                code="DOWNLOAD_INVALID_TOKEN",
            )
        return parts[0]

    async def _open_with_retry(self, path: Path):
        last_error: Exception | None = None
        for attempt in range(1, self._settings.retry.attempts + 1):
            try:
                handle = path.open("rb")
            except self._retryable as exc:
                last_error = exc
                if attempt == self._settings.retry.attempts:
                    self._metrics.retry_exhaustion_total.inc()
                    self._metrics.retry_total.labels(outcome="failure").inc()
                    break
                self._metrics.retry_total.labels(outcome="retry").inc()
                delay = self._backoff_delay(attempt, seed=str(path))
                await self._sleep(delay)
            else:
                if attempt > 1:
                    self._metrics.retry_total.labels(outcome="success").inc()
                return handle
        if last_error is None:
            last_error = FileNotFoundError(str(path))
        raise last_error

    def _backoff_delay(self, attempt: int, *, seed: str) -> float:
        base = self._settings.retry.base_delay * (2 ** (attempt - 1))
        digest = hashlib.blake2s(f"{seed}:{attempt}".encode("utf-8"), digest_size=4).digest()
        jitter = int.from_bytes(digest, "big") / 2**32
        return base + jitter * (self._settings.retry.base_delay / 2)

    def _iter_file(self, file_handle, *, start: int, end: int) -> AsyncIterator[bytes]:
        async def iterator() -> AsyncIterator[bytes]:
            try:
                if start > 0:
                    file_handle.seek(start)
                remaining = max(end - start + 1, 0)
                while remaining > 0:
                    to_read = min(self._settings.chunk_size, remaining)
                    chunk = file_handle.read(to_read)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            finally:
                file_handle.close()

        return iterator()

    def _if_none_match(self, header_value: str | None, etag_value: str) -> bool:
        if not header_value:
            return False
        for raw in header_value.split(","):
            value = raw.strip()
            if value.startswith("W/"):
                value = value[2:].strip()
            value = value.strip('"')
            if hmac.compare_digest(value.encode("utf-8"), etag_value.encode("utf-8")):
                return True
        return False

    def _parse_range(self, header: str, size: int) -> tuple[int, int]:
        if size <= 0:
            raise DownloadError(
                "درخواست محدوده نامعتبر است.",
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                code="DOWNLOAD_INVALID_RANGE",
            )
        if not header.lower().startswith("bytes="):
            raise DownloadError(
                "درخواست محدوده نامعتبر است.",
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                code="DOWNLOAD_INVALID_RANGE",
            )
        ranges = header[6:].split(",")
        if len(ranges) != 1:
            raise DownloadError(
                "درخواست محدوده نامعتبر است.",
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                code="DOWNLOAD_INVALID_RANGE",
            )
        start_text, end_text = ranges[0].strip().split("-", 1)
        if not start_text and not end_text:
            raise DownloadError(
                "درخواست محدوده نامعتبر است.",
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                code="DOWNLOAD_INVALID_RANGE",
            )
        if not start_text:
            try:
                length = int(end_text)
            except ValueError as exc:
                raise DownloadError(
                    "درخواست محدوده نامعتبر است.",
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    code="DOWNLOAD_INVALID_RANGE",
                ) from exc
            if length <= 0:
                raise DownloadError(
                    "درخواست محدوده نامعتبر است.",
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    code="DOWNLOAD_INVALID_RANGE",
                )
            start = max(size - length, 0)
            end = size - 1
        else:
            try:
                start = int(start_text)
            except ValueError as exc:
                raise DownloadError(
                    "درخواست محدوده نامعتبر است.",
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    code="DOWNLOAD_INVALID_RANGE",
                ) from exc
            if start < 0:
                raise DownloadError(
                    "درخواست محدوده نامعتبر است.",
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    code="DOWNLOAD_INVALID_RANGE",
                )
            end = size - 1
            if end_text:
                try:
                    end = int(end_text)
                except ValueError as exc:
                    raise DownloadError(
                        "درخواست محدوده نامعتبر است.",
                        status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                        code="DOWNLOAD_INVALID_RANGE",
                    ) from exc
            if start > end:
                raise DownloadError(
                    "درخواست محدوده نامعتبر است.",
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    code="DOWNLOAD_INVALID_RANGE",
                )
        if start >= size or end >= size:
            raise DownloadError(
                "درخواست محدوده نامعتبر است.",
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                code="DOWNLOAD_INVALID_RANGE",
            )
        return start, end

    def _load_manifest(self, path: Path) -> dict[str, object]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _find_manifest_entry(self, manifest: dict[str, object], filename: str) -> dict[str, object] | None:
        files = manifest.get("files")
        if not isinstance(files, Iterable):
            return None
        for entry in files:
            if isinstance(entry, dict) and entry.get("name") == filename:
                return entry
        return None

    def _guess_mime(self, filename: str) -> str:
        mime, _ = guess_type(filename)
        return mime or "application/octet-stream"

    def _content_disposition(self, filename: str) -> str:
        safe = filename.replace("\"", "")
        quoted = quote(safe)
        return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quoted}"

    def _status_label(self, code: str) -> str:
        mapping = {
            "DOWNLOAD_NOT_FOUND": "not_found",
            "DOWNLOAD_IN_PROGRESS": "in_progress",
            "DOWNLOAD_INVALID_RANGE": "invalid_range",
            "DOWNLOAD_UNAVAILABLE": "unavailable",
        }
        return mapping.get(code, "error")

    def _error_response(self, exc: DownloadError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "fa_error_envelope": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        )


def create_download_router(
    *,
    settings: DownloadSettings,
    clock: Clock,
    metrics: DownloadMetrics,
    retryable: tuple[type[Exception], ...] = (OSError,),
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> APIRouter:
    gateway = DownloadGateway(settings=settings, clock=clock, metrics=metrics, retryable=retryable, sleeper=sleeper)
    router = APIRouter()

    async def _handler(request: Request, token: str, gateway: DownloadGateway = Depends(lambda: gateway)) -> Response:
        return await gateway.handle(request, token)

    router.add_api_route("/download/{token}", _handler, methods=["GET"], name="download_artifact")
    return router


__all__ = [
    "DownloadGateway",
    "DownloadMetrics",
    "DownloadSettings",
    "DownloadTokenPayload",
    "create_download_router",
    "encode_download_token",
]
