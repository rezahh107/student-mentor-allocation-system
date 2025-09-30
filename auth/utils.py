from __future__ import annotations

import hashlib
import json
import logging
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from src.reliability.clock import Clock

LOGGER = logging.getLogger("sso")

_DIGIT_MAP = str.maketrans(
    {
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
    }
)


def fold_digits(value: str | None) -> str | None:
    if value is None:
        return None
    return value.translate(_DIGIT_MAP)


def sanitize_scope(value: str | None) -> str:
    candidate = fold_digits((value or "").strip()) or "ALL"
    candidate = "".join(ch for ch in candidate if ch.isalnum())
    if candidate.upper() == "ALL":
        return "ALL"
    digits = "".join(ch for ch in candidate if ch.isdigit())
    if not digits:
        raise ValueError("invalid scope")
    if len(digits) > 6:
        raise ValueError("invalid scope length")
    return digits


def hash_identifier(*values: str) -> str:
    digest = hashlib.blake2b(digest_size=12)
    for value in values:
        digest.update(value.encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def masked(value: str | None) -> str:
    if not value:
        return "*"
    return hash_identifier(value)[:8]


def deterministic_jitter(seed: str, attempt: int) -> float:
    digest = hashlib.blake2b(digest_size=6)
    digest.update(seed.encode("utf-8"))
    digest.update(str(attempt).encode("ascii"))
    integer = int.from_bytes(digest.digest(), "big")
    return (integer % 37) / 100.0  # milliseconds component converted to seconds


def exponential_backoff(base: float, attempt: int, *, jitter_seed: str) -> float:
    delay = base * (2**max(0, attempt - 1))
    return delay + deterministic_jitter(jitter_seed, attempt)


def decode_base64url(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return urlsafe_b64decode(segment + padding)


def encode_base64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def parse_jwt(token: str) -> tuple[dict, dict, bytes]:
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = json.loads(decode_base64url(header_b64))
    payload = json.loads(decode_base64url(payload_b64))
    signature = decode_base64url(signature_b64)
    return header, payload, signature


def utcnow(clock: Clock) -> datetime:
    return clock.now()


def ttl_from(clock: Clock, minutes: int) -> datetime:
    return clock.now() + timedelta(minutes=minutes)


def build_sid(correlation_id: str, subject: str, *, clock: Clock) -> str:
    seed = f"{correlation_id}:{subject}:{clock.now().timestamp()}"
    return hash_identifier(seed)[:24]


def merge_claims(*sources: Mapping[str, object] | None) -> dict[str, object]:
    result: dict[str, object] = {}
    for source in sources:
        if not source:
            continue
        for key, value in source.items():
            if value is None:
                continue
            result[key] = value
    return result


def log_event(logger: logging.Logger, *, msg: str, **extra: object) -> None:
    logger.info(msg, extra=extra)


def redact_attributes(attrs: Mapping[str, object]) -> Mapping[str, object]:
    redacted: dict[str, object] = {}
    for key, value in attrs.items():
        if isinstance(value, str):
            redacted[key] = masked(value)
        else:
            redacted[key] = value
    return redacted


def ensure_no_pii(payload: Mapping[str, object], *, forbidden_keys: Iterable[str]) -> None:
    for key in forbidden_keys:
        if key in payload and isinstance(payload[key], str) and "@" in payload[key]:
            raise ValueError("PII detected")
