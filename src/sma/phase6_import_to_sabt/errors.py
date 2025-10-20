"""Shared Persian error envelopes for ImportToSabt exports."""

from __future__ import annotations

from dataclasses import dataclass


EXPORT_VALIDATION_FA_MESSAGE = "درخواست نامعتبر است؛ فرمت فایل/محدوده را بررسی کنید."
EXPORT_IO_FA_MESSAGE = "خطا در تولید فایل؛ لطفاً دوباره تلاش کنید."
RATE_LIMIT_FA_MESSAGE = "تعداد درخواست‌ها از حد مجاز عبور کرده است؛ بعداً تلاش کنید."


@dataclass(frozen=True)
class ErrorEnvelope:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"error_code": self.code, "message": self.message}


def make_error(code: str, message: str) -> ErrorEnvelope:
    return ErrorEnvelope(code=code, message=message)


__all__ = [
    "ErrorEnvelope",
    "EXPORT_IO_FA_MESSAGE",
    "EXPORT_VALIDATION_FA_MESSAGE",
    "RATE_LIMIT_FA_MESSAGE",
    "make_error",
]
