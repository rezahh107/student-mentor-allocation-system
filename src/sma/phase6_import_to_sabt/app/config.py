from __future__ import annotations

from functools import lru_cache
import unicodedata
from typing import Optional

import sma.core.clock as core_clock
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ZERO_WIDTH = ("\u200c", "\u200d", "\ufeff")
_MAX_TZ_LENGTH = 255
_TZ_ERROR = "CONFIG_TZ_INVALID: «مقدار TIMEZONE نامعتبر است؛ لطفاً یک ناحیهٔ زمانی IANA معتبر وارد کنید.»"


class RateLimitConfig(BaseModel):
    namespace: str = Field(default="imports")
    requests: int = Field(default=30, ge=1)
    window_seconds: int = Field(default=60, ge=1)
    penalty_seconds: int = Field(default=120, ge=1)


class AuthConfig(BaseModel):
    metrics_token: str = Field(default="", min_length=0)
    service_token: str = Field(default="", min_length=0)
    tokens_env_var: str = Field(default="TOKENS", min_length=3)
    download_signing_keys_env_var: str = Field(default="DOWNLOAD_SIGNING_KEYS", min_length=8)
    download_url_ttl_seconds: int = Field(default=900, ge=60, le=86_400)


class RedisConfig(BaseModel):
    dsn: str = Field(..., description="Redis connection string")
    namespace: str = Field(default="import_to_sabt")
    operation_timeout: float = Field(default=0.2, ge=0.05, le=2.0)


class DatabaseConfig(BaseModel):
    dsn: str = Field(...)
    statement_timeout_ms: int = Field(default=500, ge=100, le=10_000)


class ObservabilityConfig(BaseModel):
    service_name: str = Field(default="import-to-sabt")
    metrics_namespace: str = Field(default="import_to_sabt")


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMPORT_TO_SABT_",
        env_nested_delimiter="__",  # برای پارس متغیرهای تودرتو به فرم SECTION__FIELD
        extra="forbid",
    )

    redis: RedisConfig
    database: DatabaseConfig
    auth: AuthConfig
    ratelimit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    timezone: str = Field(default="Asia/Tehran")
    readiness_timeout_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    health_timeout_seconds: float = Field(default=0.2, ge=0.1, le=5.0)
    enable_debug_logs: bool = Field(default=False)
    enable_diagnostics: bool = Field(default=False)

    @field_validator("timezone", mode="before")
    @classmethod
    def _validate_timezone(cls, value: object) -> str:
        """Normalize and validate the configured IANA timezone name."""

        if value is None:
            raise ValueError(_TZ_ERROR)

        raw = str(value)
        normalized = unicodedata.normalize("NFKC", raw)
        normalized = normalized.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)
        for char in _ZERO_WIDTH:
            normalized = normalized.replace(char, "")
        normalized = normalized.strip()

        if not normalized or len(normalized) > _MAX_TZ_LENGTH:
            raise ValueError(_TZ_ERROR)

        try:
            core_clock.validate_timezone(normalized)
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError(_TZ_ERROR) from exc

        return normalized


    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration from environment variables deterministically."""

        return cls()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig.from_env()


__all__ = [
    "AppConfig",
    "AuthConfig",
    "DatabaseConfig",
    "ObservabilityConfig",
    "RateLimitConfig",
    "RedisConfig",
    "get_config",
]
