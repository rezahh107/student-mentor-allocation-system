from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable
from uuid import uuid4
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from mimetypes import guess_type

from sma.phase6_import_to_sabt.clock import Clock, ensure_clock
# from sma.phase6_import_to_sabt.observability import MetricsCollector # حذف شد یا تغییر کرد


logger = logging.getLogger(__name__)

_CHUNK_SIZE = 64 * 1024
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY = 0.01


# --- کلاس DownloadError حذف شد ---
# class DownloadError(Exception): ...
# --- پایان حذف ---

# --- کلاس DownloadTokenPayload حذف شد ---
# @dataclass(frozen=True)
# class DownloadTokenPayload: ...
# --- پایان حذف ---

@dataclass(slots=True)
class DownloadRetryPolicy:
    attempts: int = _DEFAULT_MAX_ATTEMPTS
    base_delay: float = _DEFAULT_BASE_DELAY


# --- کلاس SignatureSecurityConfig حذف شد ---
# @dataclass(slots=True)
# class SignatureSecurityConfig: ...
# --- پایان حذف ---

# --- کلاس SignatureSecurityManager حذف شد ---
# class SignatureSecurityManager: ...
# --- پایان حذف ---


# --- کلاس DownloadMetrics ساده شد ---
class DownloadMetrics:
    """Prometheus metrics for the download gateway."""

    def __init__(self, registry) -> None: # بدون CollectorRegistry اختیاری
        self.registry = registry
        # اکنون فقط چند متریک اصلی یا هیچ متریکی ایجاد می‌شود، یا فقط یک ساختار ساده برای جلوگیری از خطا
        # این بستگی به این دارد که آیا سایر بخش‌ها به این کلاس وابسته‌ای دارند که متریک‌ها را استفاده می‌کنند.

    def observe_bytes(self, length: int) -> None:
        # عملیات واقعی حذف شد
        pass

    def requests_total(self, labels): # ساختار ساده برای جلوگیری از خطا در صورت استفاده
        class _Counter:
            def inc(self, n=1): pass
        return _Counter()

    def invalid_token_total(self): # ساختار ساده برای جلوگیری از خطا در صورت استفاده
        class _Counter:
            def inc(self, n=1): pass
        return _Counter()

    def not_found_total(self): # ساختار ساده برای جلوگیری از خطا در صورت استفاده
        class _Counter:
            def inc(self, n=1): pass
        return _Counter()

    def retry_total(self, labels): # ساختار ساده برای جلوگیری از خطا در صورت استفاده
        class _Counter:
            def inc(self, n=1): pass
        return _Counter()

    def retry_exhaustion_total(self): # ساختار ساده برای جلوگیری از خطا در صورت استفاده
        class _Counter:
            def inc(self, n=1): pass
        return _Counter()

    def range_requests_total(self, labels): # ساختار ساده برای جلوگیری از خطا در صورت استفاده
        class _Counter:
            def inc(self, n=1): pass
        return _Counter()
# --- پایان ساده‌سازی ---


@dataclass(slots=True)
class DownloadSettings:
    workspace_root: Path
    # secret: bytes # حذف شد، دیگر مورد نیاز نیست
    retry: DownloadRetryPolicy
    chunk_size: int = _CHUNK_SIZE


# --- توابع رمزگذاری/رمزگشایی توکن ساده شدند ---
def encode_download_token(payload: dict, *, secret: bytes) -> str:
    """تابع ایجاد توکن ساده شده."""
    # در محیط توسعه، فقط یک رشته ساده یا هش از پیلود ایجاد می‌کنیم
    # این فقط برای جلوگیری از خطا در صورت استفاده است
    import secrets
    return secrets.token_urlsafe(16) # یا هر چیز دیگری

def decode_download_token(token: str, *, secret: bytes, clock: Clock) -> dict:
    """تابع تأیید توکن ساده شده."""
    # در محیط توسعه، همیشه یک پیلود ساختگی یا از قبل تعریف شده برمی‌گردانیم
    # این فقط برای جلوگیری از خطا در صورت استفاده است
    # فرض می‌کنیم توکن یک نام فایل است
    # این تابع دیگر امضای واقعی را بررسی نمی‌کند
    # ممکن است نیاز باشد تا این تابع کاملاً حذف یا جایگزین شود
    # برای اینکه gateway بتواند کار کند، یک ساختار مشابه payload ایجاد می‌کنیم
    # فرض می‌کنیم token همان نام فایل است یا شامل اطلاعات مورد نیاز است
    # برای سادگی، یک پیلود ثابت یا یک پیلود ساخته شده از token برمی‌گردانیم
    # این کار باید با تغییرات gateway هماهنگ شود
    # برای اینجا، فرض می‌کنیم یک توکن معتبر است و یک پیلود ساده برمی‌گردانیم
    # مثلاً: "namespace/filename/sha256/size/exp" -> یک دیکشنری
    # اما برای سادگی بیشتر، فقط یک پیلود پیش‌فرض برمی‌گردانیم یا از gateway مستقیماً استفاده می‌کنیم
    # بنابراین، این تابع را می‌توان کاملاً حذف کرد یا فقط یک مقدار پیش‌فرض برمی‌گرداند.
    # توجه: این تغییر باید با gateway هماهنگ شود.
    # از آنجا که gateway قبلاً decode_download_token را فراخوانی می‌کرد، اکنون باید آن را حذف کنیم.
    # پس این تابع نیز بی‌استفاده می‌شود و می‌توانیم آن را خالی یا پیش‌فرض نگه داریم.
    return {
        "namespace": "dev",
        "filename": token,
        "sha256": "dev_sha256_placeholder",
        "size": 1024, # یا مقدار واقعی بعداً محاسبه شود
        "exp": int(clock.now().timestamp()) + 3600 # منقضی نشود
    }
# --- پایان تغییر ---


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
        # observer: MetricsCollector | None = None, # حذف شد یا تغییر کرد
        # security: SignatureSecurityManager | None = None, # حذف شد
        retryable: tuple[type[Exception], ...] = (OSError,),
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = DownloadSettings(
            workspace_root=settings.workspace_root.resolve(),
            # secret=settings.secret, # حذف شد
            retry=settings.retry,
            chunk_size=settings.chunk_size,
        )
        self._clock = ensure_clock(clock, timezone="Asia/Tehran")
        self._metrics = metrics
        # self._observer = observer # حذف شد
        # self._security = security # حذف شد
        self._retryable = retryable
        self._sleep = sleeper or (lambda duration: asyncio.sleep(duration))

    async def handle(self, request: Request, token: str) -> Response:
        correlation_id = request.headers.get("X-Request-ID") or getattr(
            request.state, "correlation_id", str(uuid4())
        )
        # client_id = request.client.host if request.client else "anonymous" # حذف شد
        # if self._security is not None and await self._security.is_blocked(client_id): ... # حذف شد

        # --- تأیید توکن حذف شد ---
        # try:
        #     payload = decode_download_token(token, secret=self._settings.secret, clock=self._clock)
        # except DownloadError as exc: ...
        # فرض می‌کنیم token همان نام فایل است
        payload = {
            "namespace": "dev",
            "filename": token,
            "sha256": "dev_sha256_placeholder",
            "size": 0, # بعداً محاسبه می‌شود
            "exp": int(self._clock.now().timestamp()) + 3600
        }
        # --- پایان تغییر ---

        context = DownloadContext(
            correlation_id=correlation_id,
            namespace=payload["namespace"],
            filename=payload["filename"],
            sha_prefix=payload["sha256"][:12],
            range_start=None,
            range_end=None,
            artifact_size=None,
        )

        # --- ثبت موفقیت/شکست امنیتی حذف شد ---
        # if self._observer is not None:
        #     self._observer.record_signature_success()
        # if self._security is not None:
        #     await self._security.record_success(client_id)
        # --- پایان حذف ---

        # فراخوانی مستقیم _serve بدون تأیید توکن
        try:
            return await self._serve(request, payload, context)
        except Exception as exc: # جایگزین DownloadError
            logger.warning("download.failure", extra={"event": "DOWNLOAD_ERROR_GENERIC", **context.as_log(), "error": str(exc)})
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "fa_error_envelope": {
                        "code": "DOWNLOAD_ERROR_GENERIC",
                        "message": "خطای داخلی سرور.",
                    }
                },
                headers={"X-Request-ID": context.correlation_id},
            )


    async def _serve(
        self,
        request: Request,
        payload: dict, # اکنون یک دیکشنری ساده است
        context: DownloadContext,
    ) -> Response:
        # namespace = self._sanitize_segment(payload.namespace) # حذف شد
        # filename = self._sanitize_segment(payload.filename) # حذف شد
        # namespace و filename را مستقیماً از payload می‌گیریم یا از token
        # فرض می‌کنیم namespace و filename قبلاً از token استخراج شده‌اند یا از یک مسیر مشخص آمده‌اند
        # برای سادگی، فقط filename را از payload می‌گیریم و namespace را ثابت فرض می‌کنیم
        # یا از token استخراج می‌کنیم: مثلاً token = "namespace_filename.ext"
        # اما برای سادگی بیشتر، فقط filename را از payload می‌گیریم
        filename = payload["filename"]
        namespace = payload["namespace"]

        # بررسی امنیتی مسیر حذف شد
        # workspace_root = (self._settings.workspace_root / namespace).resolve()
        # if not workspace_dir.is_dir() or not workspace_dir.is_relative_to(workspace_root): ...
        workspace_value = getattr(request.app.state, "storage_root", None)
        if workspace_value is None:
            workspace_root = self._settings.workspace_root
        else:
            workspace_root = Path(workspace_value)
        workspace_root = workspace_root.resolve()
        namespace_dir = (workspace_root / namespace).resolve()
        # توجه: بررسی is_relative_to حذف شد، که می‌تواند یک خطر امنیتی باشد، اما برای توسعه محلی پذیرفتنی است
        # اینجا فقط یک نگرانی است، اما هدف ما حذف امنیت است
        # بنابراین فقط چک می‌کنیم که دایرکتوری وجود دارد
        if not namespace_dir.exists():
             logger.warning("download.failure", extra={"event": "NAMESPACE_NOT_FOUND", **context.as_log()})
             return JSONResponse(
                 status_code=status.HTTP_404_NOT_FOUND,
                 content={
                     "fa_error_envelope": {
                         "code": "DOWNLOAD_NOT_FOUND",
                         "message": "شیء درخواستی یافت نشد.",
                     }
                 },
                 headers={"X-Request-ID": context.correlation_id},
             )

        # بررسی فایل‌های .part حذف شد
        # if any(namespace_dir.glob("*.part")): ...

        # بارگذاری و تأیید منیفست حذف شد
        # manifest_path = namespace_dir / "export_manifest.json"
        # manifest = self._load_manifest(manifest_path)
        # manifest_entry = self._find_manifest_entry(manifest, filename)
        # expected_sha = manifest_entry.get("sha256")
        # expected_size = int(manifest_entry.get("byte_size", payload.size))
        # if expected_sha != payload.sha256 or expected_size != payload.size: ...

        # مسیر هدف فایل
        # target = (namespace_dir / filename).resolve()
        # if not target.is_file() or not target.is_relative_to(namespace_dir): ...
        # بررسی is_relative_to حذف شد
        target = namespace_dir / filename
        if not target.is_file():
             logger.warning("download.failure", extra={"event": "FILE_NOT_FOUND", **context.as_log()})
             return JSONResponse(
                 status_code=status.HTTP_404_NOT_FOUND,
                 content={
                     "fa_error_envelope": {
                         "code": "DOWNLOAD_NOT_FOUND",
                         "message": "شیء درخواستی یافت نشد.",
                     }
                 },
                 headers={"X-Request-ID": context.correlation_id},
             )

        # بررسی اندازه واقعی با اندازه اعلام شده در توکن حذف شد
        actual_size = target.stat().st_size
        # if actual_size != expected_size: ...
        context.artifact_size = actual_size

        # تأیید ETag حذف شد
        # etag_value = expected_sha.lower()
        # if self._if_none_match(request.headers.get("if-none-match"), etag_value): ...

        # بررسی درخواست محدوده (Range) ممکن است حذف شود یا ساده شود
        range_header = request.headers.get("range")
        range_slice: tuple[int, int] | None = None
        if range_header:
            try:
                range_slice = self._parse_range(range_header, actual_size)
            except ValueError: # جایگزین DownloadError
                self._metrics.range_requests_total(labels={"status": "rejected"}).inc() # یا فقط لاگ
                logger.warning("download.failure", extra={"event": "INVALID_RANGE_HEADER", **context.as_log(), "range": range_header})
                return JSONResponse(
                    status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                    content={
                        "fa_error_envelope": {
                            "code": "DOWNLOAD_INVALID_RANGE",
                            "message": "درخواست محدوده نامعتبر است.",
                        }
                    },
                    headers={"X-Request-ID": context.correlation_id},
                )
            else:
                self._metrics.range_requests_total(labels={"status": "accepted"}).inc() # یا فقط لاگ
        else:
            self._metrics.range_requests_total(labels={"status": "absent"}).inc() # یا فقط لاگ

        # باز کردن فایل (بدون تأیید امنیتی)
        # file_handle = await self._open_with_retry(target) # می‌تواند باز شود، اما ترجیحاً باز کردن مستقیم
        # برای StreamingResponse، معمولاً نیازی به باز کردن دستی نیست، فقط یک جنراتور لازم است
        # بنابراین، تابع _iter_file را مستقیماً می‌سازیم

        if actual_size == 0:
            start, end = 0, -1
        elif range_slice:
            start, end = range_slice
        else:
            start, end = 0, actual_size - 1
        context.range_start = start if range_slice else None
        context.range_end = end if range_slice else None

        # تابع جنراتور فایل
        def iter_file(start=start, end=end):
            with target.open("rb") as f:
                if start > 0:
                    f.seek(start)
                remaining = max(end - start + 1, 0)
                while remaining > 0:
                    to_read = min(self._settings.chunk_size, remaining)
                    chunk = f.read(to_read)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        length = max(end - start + 1, 0)
        # headers = {"Content-Disposition": ..., "Content-Type": ..., ...}
        headers = {
            "Content-Disposition": self._content_disposition(filename),
            "Content-Type": self._guess_mime(filename),
            "Accept-Ranges": "bytes",
            # "ETag": f'"{etag_value}"', # حذف شد
            "X-Request-ID": context.correlation_id,
        }
        if range_slice:
            headers["Content-Range"] = f"bytes {start}-{end}/{actual_size}"
            status_code = status.HTTP_206_PARTIAL_CONTENT
            # self._metrics.requests_total.labels(status="partial").inc() # حذف شد یا تغییر کرد
        else:
            status_code = status.HTTP_200_OK
            # self._metrics.requests_total.labels(status="success").inc() # حذف شد یا تغییر کرد
        headers["Content-Length"] = str(length)

        response = StreamingResponse(iter_file(), media_type=headers["Content-Type"], status_code=status_code, headers=headers)
        # self._metrics.observe_bytes(length) # حذف شد یا تغییر کرد
        logger.info("download.served", extra={"event": "DOWNLOAD_OK", **context.as_log(), "bytes": length})
        return response

    # بقیه توابع مانند _sanitize_segment، _open_with_retry، _iter_file (که جایگزین شد)،
    # _if_none_match، _parse_range، _load_manifest، _find_manifest_entry،
    # _guess_mime، _content_disposition، _status_label، _error_response
    # باید یا حذف یا تغییر کنند.

    # _sanitize_segment حذف شد چون دیگر مورد نیاز نیست (بررسی امنیتی مسیر)

    # _open_with_retry حذف شد چون فایل مستقیماً در جنراتور باز می‌شود

    # _iter_file جایگزین شد

    def _if_none_match(self, header_value: str | None, etag_value: str) -> bool:
        # این تابع دیگر کاربرد ندارد چون ETag حذف شد
        return False # تغییر داده شد

    def _parse_range(self, header: str, size: int) -> tuple[int, int]:
        # این تابع حذف یا ساده شود
        # اگر می‌خواهیم range را هم حذف کنیم، فقط یک مقدار پیش‌فرض برگردانیم
        # اما اگر range پشتیبانی شود، این تابع باید باقی بماند یا ساده شود
        # در اینجا، ما آن را بازنویسی می‌کنیم تا خطا ندهد، اما ممکن است دقیقاً همان کار قبلی را نکند
        # اما برای توسعه، می‌توانیم آن را نگه داریم یا یک نسخه ساده‌تر بنویسیم
        # توجه: این تابع دیگر DownloadError نمی‌اندازد، بلکه ValueError می‌اندازد
        if size <= 0:
            raise ValueError("size must be positive")
        if not header.lower().startswith("bytes="):
            raise ValueError("invalid range header format")
        ranges = header[6:].split(",")
        if len(ranges) != 1:
            raise ValueError("multiple ranges not supported")
        start_text, end_text = ranges[0].strip().split("-", 1)
        if not start_text and not end_text:
            raise ValueError("invalid range syntax")
        if not start_text:
            try:
                length = int(end_text)
            except ValueError:
                raise ValueError("invalid range value")
            if length <= 0:
                raise ValueError("length must be positive")
            start = max(size - length, 0)
            end = size - 1
        else:
            try:
                start = int(start_text)
            except ValueError:
                raise ValueError("invalid range value")
            if start < 0:
                raise ValueError("start must be non-negative")
            end = size - 1
            if end_text:
                try:
                    end = int(end_text)
                except ValueError:
                    raise ValueError("invalid range value")
            if start > end:
                raise ValueError("start must be <= end")
        if start >= size or end >= size:
            raise ValueError("range out of bounds")
        return start, end

    # _load_manifest و _find_manifest_entry حذف شدند چون دیگر منیفست بررسی نمی‌شود

    def _guess_mime(self, filename: str) -> str:
        mime, _ = guess_type(filename)
        return mime or "application/octet-stream"

    def _content_disposition(self, filename: str) -> str:
        safe = filename.replace("\"", "")
        quoted = quote(safe)
        return f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quoted}"

    # _status_label و _error_response دیگر مورد نیاز نیستند چون DownloadError حذف شد


def create_download_router(
    *,
    settings: DownloadSettings,
    clock: Clock,
    metrics: DownloadMetrics,
    # observer: MetricsCollector | None = None, # حذف شد یا تغییر کرد
    # security: SignatureSecurityManager | None = None, # حذف شد
    retryable: tuple[type[Exception], ...] = (OSError,),
    sleeper: Callable[[float], Awaitable[None]] | None = None,
) -> APIRouter:
    gateway = DownloadGateway(
        settings=settings,
        clock=clock,
        metrics=metrics,
        # observer=observer, # حذف شد
        # security=security, # حذف شد
        retryable=retryable,
        sleeper=sleeper,
    )
    router = APIRouter()

    async def _handler(request: Request, token: str, gateway: DownloadGateway = Depends(lambda: gateway)) -> Response:
        return await gateway.handle(request, token)

    # توجه: endpoint ممکن است باید تغییر کند، مثلاً به /download/files/{filename}
    # اما بر اساس خروجی کدکس، endpoint `/downloads/{token_id}` در app_factory.py تعریف شده بود
    # و احتمالاً download_router در آنجا استفاده شده بود.
    # اما در این فایل، endpoint `/download/{token}` تعریف شده است.
    # خروجی کدکس شامل `/downloads/{token_id}` بود که نشان می‌دهد endpoint در app_factory.py تعریف شده.
    # پس احتمالاً این router در app_factory.py به یک endpoint دیگری mount می‌شود یا تغییر می‌کند.
    # اما بر اساس این فایل، endpoint `/download/{token}` است.
    # ما endpoint را همانطور که هست نگه می‌داریم، اما gateway را تغییر می‌دهیم.
    router.add_api_route("/download/{token}", _handler, methods=["GET"], name="download_artifact")
    return router


__all__ = [
    "DownloadGateway",
    "DownloadMetrics",
    "DownloadSettings",
    # "DownloadTokenPayload", # حذف شد
    # "SignatureSecurityConfig", # حذف شد
    # "SignatureSecurityManager", # حذف شد
    "create_download_router",
    # "encode_download_token", # ممکن است حذف شود، اما اگر فایل‌های دیگر به آن وابستگی داشتند، می‌توان نگه داشت
    # برای سازگاری، می‌توانیم encode_download_token را نگه داریم، اما ساده شده
    "encode_download_token",
]
