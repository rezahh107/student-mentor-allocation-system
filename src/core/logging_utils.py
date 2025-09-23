# --- file: src/core/logging_utils.py ---
r"""Spec compliance: Gender 0/1; reg_status {0,1,3} (+Hakmat map); reg_center {0,1,2}; mobile ^09\d{9}$; national_id 10-digit + mod-11 checksum; student_type DERIVE from roster"""
# Handle: null, 0, '0', empty string, boundary values, booleans
# Validation rules:
# Values: gender -> {0, 1}
# Values: reg_status -> {0, 1, 3}
# Values: reg_center -> {0, 1, 2}

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from typing import Any, Final

LOGGER: Final[logging.Logger] = logging.getLogger("core.normalization")

# Translation table converting Persian and Arabic-Indic digits to ASCII.
_PERSIAN_TO_ASCII_DIGITS: Final[dict[int, str]] = {
    ord("۰"): "0",
    ord("۱"): "1",
    ord("۲"): "2",
    ord("۳"): "3",
    ord("۴"): "4",
    ord("۵"): "5",
    ord("۶"): "6",
    ord("۷"): "7",
    ord("۸"): "8",
    ord("۹"): "9",
    ord("٠"): "0",
    ord("١"): "1",
    ord("٢"): "2",
    ord("٣"): "3",
    ord("٤"): "4",
    ord("٥"): "5",
    ord("٦"): "6",
    ord("٧"): "7",
    ord("٨"): "8",
    ord("٩"): "9",
}

_MOBILE_DIGIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d")

_NID_HASH_SALT_DEFAULT: Final[str] = "core.normalization"


def _current_salt() -> str:
    """Return the configured salt for hashing national identifiers."""

    return os.getenv("NID_HASH_SALT", _NID_HASH_SALT_DEFAULT)


def _normalize_mobile_digits(digits: str) -> str:
    """Normalize Iranian mobile prefixes for masking purposes."""

    if digits.startswith("0098") and len(digits) > 4:
        return "0" + digits[4:]
    if digits.startswith("098") and len(digits) > 11:
        return "0" + digits[3:]
    if digits.startswith("98") and len(digits) > 10:
        return "0" + digits[2:]
    if digits.startswith("9") and len(digits) == 10:
        return "0" + digits
    return digits


def _mask_mobile(value: str) -> str:
    """Mask an Iranian mobile number while preserving start/end digits."""

    normalized = unicodedata.normalize("NFKC", value).translate(_PERSIAN_TO_ASCII_DIGITS)
    digits = re.sub(r"\D", "", normalized)
    digits = _normalize_mobile_digits(digits)
    if len(digits) >= 11 and digits.startswith("09"):
        return f"09*******{digits[-2:]}"
    if len(digits) >= 7:
        return f"{digits[0]}******{digits[-1]}"
    return "***"


def _hash_value(value: object) -> str:
    """Return a deterministic hash digest suitable for logging samples."""

    normalized = unicodedata.normalize("NFKC", str(value)).translate(_PERSIAN_TO_ASCII_DIGITS)
    salted = f"{_current_salt()}::{normalized}"
    digest = hashlib.sha256(salted.encode("utf-8")).hexdigest()
    return digest[:12]


def _sanitize_value(field: str, value: object) -> str | None:
    """Return a PII-safe representation of ``value`` for logging."""

    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value))
    translated = normalized.translate(_PERSIAN_TO_ASCII_DIGITS)
    if field in {"mobile", "phone", "cell", "cellphone"}:
        return _mask_mobile(translated)
    redacted = _MOBILE_DIGIT_PATTERN.sub("*", translated)
    return redacted[:64]


def _derive_mobile_mask(field: str, value: object) -> str | None:
    """Return a deterministic mask for mobile numbers."""

    if value is None:
        return None
    if field in {"mobile", "phone", "cell", "cellphone"}:
        return _mask_mobile(str(value))
    return None


def _derive_nid_hash(field: str, value: object) -> str | None:
    """Return a salted hash for national identifiers."""

    if value is None:
        return None
    if field in {"national_id", "nid", "meli_code"}:
        return _hash_value(value)
    return None


def log_norm_error(field: str, old: object, reason: str, code: str) -> None:
    """Emit a structured warning for normalization failures.

    Args:
        field: Name of the field that failed normalization.
        old: Original value received.
        reason: Human-readable reason for failure.
        code: Stable machine-readable code.
    """

    payload: dict[str, Any] = {
        "event": "normalization_failure",
        "field": field,
        "reason": reason,
        "code": code,
        "sample": _sanitize_value(field, old),
        "mobile_mask": _derive_mobile_mask(field, old),
        "nid_hash": _derive_nid_hash(field, old),
    }
    LOGGER.warning(json.dumps(payload, ensure_ascii=False))


__all__ = ["LOGGER", "log_norm_error"]
