from __future__ import annotations

import dataclasses
import json
import os
import re
import secrets
from typing import Any, Mapping, MutableMapping
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from prometheus_client import CollectorRegistry, Counter, generate_latest


_MASK = "***REDACTED***"
_SENSITIVE_KEYS = {
    "token",
    "secret",
    "password",
    "credential",
    "key",
    "authorization",
    "auth",
}


class JsonLogger:
    """Utility for emitting structured, redacted JSON logs."""

    @classmethod
    def redact(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls._redact_string(value)
        if isinstance(value, Mapping):
            sanitized: MutableMapping[Any, Any] = {}
            for key, item in value.items():
                if isinstance(key, str) and cls._is_sensitive_key(key):
                    sanitized[key] = _MASK
                    continue
                sanitized_key = cls._redact_string(key) if isinstance(key, str) else key
                sanitized[sanitized_key] = cls.redact(item)
            return dict(sanitized)
        if isinstance(value, (list, tuple, set)):
            return type(value)(cls.redact(item) for item in value)
        return value

    @classmethod
    def dumps(cls, payload: Any) -> str:
        return json.dumps(cls.redact(payload), ensure_ascii=False, sort_keys=True)

    @classmethod
    def _is_sensitive_key(cls, key: str) -> bool:
        normalized = key.lower()
        return any(token in normalized for token in _SENSITIVE_KEYS)

    @classmethod
    def _redact_string(cls, text: str) -> str:
        if not text:
            return text
        metrics_token = os.environ.get("METRICS_TOKEN")
        if metrics_token:
            text = text.replace(metrics_token, _MASK)
        text = re.sub(r"(?i)(bearer)\s+[A-Za-z0-9._\-]{6,}", lambda m: f"{m.group(1).title()} {_MASK}", text)
        text = re.sub(
            r"(?i)(token|secret|password|key|credential|auth)=([^&\s]+)",
            lambda m: f"{m.group(1)}={_MASK}",
            text,
        )
        parsed = urlparse(text)
        if parsed.scheme and parsed.netloc and (parsed.query or parsed.username):
            sanitized_query = cls._sanitize_query(parsed.query)
            sanitized_username = _MASK if parsed.username else None
            parsed = parsed._replace(query=sanitized_query)
            if sanitized_username:
                netloc = parsed.hostname or ""
                if parsed.port:
                    netloc = f"{netloc}:{parsed.port}"
                parsed = parsed._replace(netloc=netloc)
            text = urlunparse(parsed)
        return text

    @classmethod
    def _sanitize_query(cls, query: str) -> str:
        if not query:
            return ""
        pairs = parse_qsl(query, keep_blank_values=True)
        sanitized: list[tuple[str, str]] = []
        for key, value in pairs:
            if cls._is_sensitive_key(key):
                sanitized.append((key, _MASK))
            else:
                sanitized.append((key, value))
        return urlencode(sanitized, doseq=True)


@dataclasses.dataclass
class DoctorMetrics:
    """Prometheus metrics wrapper for Reqs Doctor operations."""

    registry: CollectorRegistry
    prefix: str = "reqs_doctor"

    def __post_init__(self) -> None:
        self.plan_generated = Counter(
            f"{self.prefix}_plan_generated_total",
            "Total number of plans generated",
            labelnames=(),
            registry=self.registry,
        )
        self.fix_applied = Counter(
            f"{self.prefix}_fix_applied_total",
            "Total number of fixes applied",
            labelnames=(),
            registry=self.registry,
        )
        self.retry_exhaustion = Counter(
            f"{self.prefix}_retry_exhaustion_total",
            "Number of times retries were exhausted",
            labelnames=(),
            registry=self.registry,
        )

    def observe_plan(self) -> None:
        self.plan_generated.labels().inc()

    def observe_fix(self) -> None:
        self.fix_applied.labels().inc()

    def observe_retry_exhaustion(self) -> None:
        self.retry_exhaustion.labels().inc()

    @classmethod
    def fresh(cls, prefix: str = "reqs_doctor") -> "DoctorMetrics":
        return cls(CollectorRegistry(), prefix=prefix)


def serve_metrics_guarded(
    metrics: DoctorMetrics,
    *,
    headers: Mapping[str, str] | None = None,
    header_name: str = "X-Metrics-Token",
) -> tuple[int, Mapping[str, str], bytes]:
    expected = os.environ.get("METRICS_TOKEN")
    if not expected:
        return (
            503,
            {"Content-Type": "text/plain; charset=utf-8"},
            "توکن سنجه پیکربندی نشده است.".encode("utf-8"),
        )
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    provided = headers.get(header_name.lower())
    if not provided:
        return (
            401,
            {"Content-Type": "text/plain; charset=utf-8"},
            "دسترسی به /metrics نیازمند توکن معتبر است.".encode("utf-8"),
        )
    if not secrets.compare_digest(provided, expected):
        return (
            403,
            {"Content-Type": "text/plain; charset=utf-8"},
            "توکن ارائه‌شده نامعتبر است.".encode("utf-8"),
        )
    payload = generate_latest(metrics.registry)
    return (
        200,
        {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
        payload,
    )
