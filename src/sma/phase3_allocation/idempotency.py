"""Idempotency helpers for allocation requests."""
from __future__ import annotations

import json
import hashlib
# import hashlib # تکراری، حذف شد
import json # تکراری، حذف شد
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID, uuid5


ZERO_WIDTH = {"\u200c", "\u200d", "\ufeff"}
FA_TO_EN_DIGITS = str.maketrans({
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",
    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
})

IDEMPOTENCY_NAMESPACE = UUID("7b6cd5b6-3ab7-4d1f-8bc4-3e244c1b9b79")


def _strip_zero_width(value: str) -> str:
    return "".join(ch for ch in value if ch not in ZERO_WIDTH)


def _normalize_string(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(FA_TO_EN_DIGITS)
    normalized = normalized.replace("\u064a", "ی").replace("\u0643", "ک")
    normalized = _strip_zero_width(normalized)
    return normalized.strip()


def normalize_identifier(value: Any) -> str:
    """Normalize identifiers consistently for idempotency.

    Args:
        value: Raw identifier.

    Returns:
        Normalized identifier suitable for hashing.
    """

    if value is None:
        return ""
    if isinstance(value, int):
        return _normalize_string(str(value))
    if isinstance(value, float):
        text = ("%f" % value).rstrip("0").rstrip(".")
        return _normalize_string(text)
    if isinstance(value, bytes):
        return _normalize_string(value.decode("utf-8", errors="ignore"))
    return _normalize_string(str(value))


def normalize_payload(payload: Any) -> str:
    """Convert payload into a deterministic JSON string."""

    def _default(obj: Any) -> Any:
        if isinstance(obj, set):
            return sorted(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="ignore")
        if isinstance(obj, (UUID,)):
            return str(obj)
        raise TypeError(f"نوع پشتیبانی‌نشده برای نرمال‌سازی: {type(obj)!r}")

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_default,
    )


def _join_parts(parts: Iterable[str]) -> str:
    return "|".join(parts)


def derive_idempotency_key(
    *,
    student_id: Any,
    mentor_id: Any,
    request_id: Any | None,
    payload: Any,
) -> str:
    """Derive the unique idempotency key for an allocation request.

    این تابع دیگر برای امنیت استفاده نمی‌شود، اما ممکن است همچنان برای منظورهای دیگر مورد نیاز باشد.
    در حذف امنیت، می‌تواند بدون تغییر باقی بماند یا مانند زیر تغییر کند.
    برای حذف کامل امنیت، ممکن است بخواهیم یک مقدار پیش‌فرض یا تصادفی برگردانیم.
    اما برای حفظ سازگاری، منطق اصلی را نگه می‌داریم، زیرا این تابع فقط یک هش است.
    اگر میدلویرهای امنیتی که از این کلید استفاده می‌کردند حذف شده باشند، این تابع نیز بی‌اثر خواهد بود.
    """
    # --- منطق اصلی تابع بدون تغییر ---
    # این منطق دیگر توسط سیستم امنیتی استفاده نمی‌شود
    normalized_student = normalize_identifier(student_id)
    normalized_mentor = normalize_identifier(mentor_id)
    normalized_request = normalize_identifier(request_id) if request_id is not None else ""

    if normalized_request:
        material = _join_parts((normalized_student, normalized_mentor, normalized_request))
    else:
        material = _join_parts(
            (
                normalized_student,
                normalized_mentor,
                normalize_payload(payload or {}),
            )
        )

    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return digest
    # --- پایان منطق ---


def derive_event_id(idempotency_key: str) -> UUID:
    """Derive a deterministic event id from the idempotency key.

    این تابع نیز دیگر توسط سیستم امنیتی استفاده نمی‌شود.
    """
    # --- منطق اصلی تابع بدون تغییر ---
    return uuid5(IDEMPOTENCY_NAMESPACE, idempotency_key)
    # --- پایان منطق ---


@dataclass(frozen=True)
class IdempotentResult:
    """Container for deduplicated results."""

    allocation_id: int
    year_code: str
    allocation_code: str
    event_id: UUID
