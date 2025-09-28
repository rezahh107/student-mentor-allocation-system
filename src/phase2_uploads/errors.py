from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class UploadError(Exception):
    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(envelope.message)
        self.envelope = envelope


UPLOAD_ERRORS = {
    "UPLOAD_VALIDATION_ERROR": ErrorEnvelope(
        code="UPLOAD_VALIDATION_ERROR",
        message="فایل نامعتبر است؛ لطفاً خطاهای اعلام‌شده را رفع کنید.",
    ),
    "UPLOAD_FORMAT_UNSUPPORTED": ErrorEnvelope(
        code="UPLOAD_FORMAT_UNSUPPORTED",
        message="فایل پشتیبانی نمی‌شود؛ فقط CSV یا ZIP مجاز است.",
    ),
    "UPLOAD_SIZE_EXCEEDED": ErrorEnvelope(
        code="UPLOAD_SIZE_EXCEEDED",
        message="حجم فایل بیش از حد مجاز است (۵۰ مگابایت).",
    ),
    "UPLOAD_INTERNAL_ERROR": ErrorEnvelope(
        code="UPLOAD_INTERNAL_ERROR",
        message="خطای غیرمنتظره رخ داد؛ لطفاً بعداً دوباره تلاش کنید.",
    ),
    "UPLOAD_CONFLICT": ErrorEnvelope(
        code="UPLOAD_CONFLICT",
        message="عملیات تکراری شناسایی شد؛ از شناسه یکتا استفاده کنید.",
    ),
    "UPLOAD_MULTIPART_INVALID": ErrorEnvelope(
        code="UPLOAD_MULTIPART_INVALID",
        message="درخواست نامعتبر است؛ بخش فایل ناقص یا مرز چندبخشی مخدوش است.",
    ),
    "UPLOAD_MULTIPART_FILE_COUNT": ErrorEnvelope(
        code="UPLOAD_MULTIPART_FILE_COUNT",
        message="درخواست نامعتبر است؛ فقط یک فایل مجاز است.",
    ),
    "UPLOAD_ACTIVATION_CONFLICT": ErrorEnvelope(
        code="UPLOAD_ACTIVATION_CONFLICT",
        message="فقط یک پرونده در هر سال تحصیلی می‌تواند فعال باشد.",
    ),
    "UPLOAD_NOT_FOUND": ErrorEnvelope(
        code="UPLOAD_NOT_FOUND",
        message="پرونده بارگذاری‌شده یافت نشد.",
    ),
}


def envelope(name: str, *, details: Optional[Dict[str, Any]] = None) -> ErrorEnvelope:
    base = UPLOAD_ERRORS[name]
    if details:
        return ErrorEnvelope(code=base.code, message=base.message, details=details)
    return base
