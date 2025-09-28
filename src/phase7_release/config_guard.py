"""Typed configuration guard with Persian diagnostics."""
from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_DIGIT_TRANSLATION = str.maketrans(
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
_ZERO_WIDTH = {"\u200c", "\u200f", "\ufeff", "\u2060"}


class ConfigValidationError(ValueError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True)
class ResolvedConfig:
    redis_url: str
    postgres_dsn: str
    metrics_token: str
    metrics_path: Path
    rate_limit_per_minute: int
    idempotency_ttl_hours: int
    profile: str
    allow_get_fail_open: bool


class _AppConfig(BaseModel):
    redis_url: str = Field(..., min_length=5)
    postgres_dsn: str = Field(..., min_length=5)
    metrics_token_env: str = Field(..., min_length=2)
    metrics_path: str = Field(..., min_length=1)
    rate_limit_per_minute: int = Field(..., ge=1, le=10000)
    idempotency_ttl_hours: int = Field(..., ge=1, le=72)
    profile: str
    allow_get_fail_open: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("redis_url", "postgres_dsn", "metrics_token_env", "metrics_path", mode="before")
    def _normalize_text(cls, value: Any) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("empty")
        return normalized

    @field_validator("profile")
    def _validate_profile(cls, value: str) -> str:
        normalized = _normalize(value)
        if normalized != "SABT_V1":
            raise ValueError("unsupported-profile")
        return normalized


class ConfigGuard:
    """Validate runtime configuration with deterministic errors."""

    def __init__(self, *, env: Mapping[str, str] | None = None) -> None:
        self._env = dict(env or os.environ)

    def parse(self, payload: Mapping[str, Any]) -> ResolvedConfig:
        try:
            config = _AppConfig(**payload)
        except ValidationError as exc:  # pragma: no cover - exercised via tests
            raise ConfigValidationError(_to_persian_error(exc)) from exc

        token_name = config.metrics_token_env
        token_value = _normalize(self._env.get(token_name))
        if not token_value:
            raise ConfigValidationError(f"«پیکربندی نامعتبر است؛ متغیر محیطی {token_name} یافت نشد.»")

        metrics_path = Path(config.metrics_path)
        if len(metrics_path.as_posix()) > 2048:
            raise ConfigValidationError("«پیکربندی نامعتبر است؛ مسیر بسیار طولانی است.»")

        return ResolvedConfig(
            redis_url=config.redis_url,
            postgres_dsn=config.postgres_dsn,
            metrics_token=token_value,
            metrics_path=metrics_path,
            rate_limit_per_minute=config.rate_limit_per_minute,
            idempotency_ttl_hours=config.idempotency_ttl_hours,
            profile=config.profile,
            allow_get_fail_open=config.allow_get_fail_open,
        )


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_DIGIT_TRANSLATION)
    for token in _ZERO_WIDTH:
        text = text.replace(token, "")
    return text.strip()


def _to_persian_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "«پیکربندی نامعتبر است؛ مقدار ناشناخته.»"
    first = errors[0]
    loc = first.get("loc", ("?",))
    field = loc[0] if isinstance(loc, (list, tuple)) and loc else loc
    if first.get("type") == "value_error.extra":
        return f"«پیکربندی نامعتبر است؛ کلید ناشناخته: {field}»"
    return f"«پیکربندی نامعتبر است؛ مقدار نامعتبر برای {field}»"


__all__ = ["ConfigGuard", "ResolvedConfig", "ConfigValidationError"]
