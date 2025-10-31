from __future__ import annotations

import unicodedata
from functools import lru_cache
import unicodedata

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import sma.core.clock as core_clock

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ZERO_WIDTH = ("\u200c", "\u200d", "\ufeff")
_MAX_TZ_LENGTH = 255
_TZ_ERROR = (
    "CONFIG_TZ_INVALID: «مقدار TIMEZONE نامعتبر است؛ لطفاً یک ناحیهٔ زمانی "
    "IANA معتبر وارد کنید.»"
)


class RedisConfig(BaseModel):
    """Minimal Redis settings for local development."""

    dsn: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string (optional in dev).",
    )
    namespace: str = Field(default="import_to_sabt")
    operation_timeout: float = Field(default=0.2, ge=0.05, le=2.0)


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    dsn: str = Field(default="postgresql://localhost:5432/import_to_sabt")
    statement_timeout_ms: int = Field(default=500, ge=100, le=10_000)


class ObservabilityConfig(BaseModel):
    service_name: str = Field(default="import-to-sabt")
    metrics_namespace: str = Field(default="import_to_sabt")


class AuthConfig(BaseModel):
    """Authentication tokens for service and metrics endpoints."""

    metrics_token: str = Field(default="", description="Bearer token for /metrics endpoint")
    service_token: str = Field(default="", description="Primary service bearer token")
    allow_all: bool = Field(
        default=True,
        description="Disable token validation for local development environments.",
    )
    tokens_env_var: str = Field(default="TOKENS")
    download_signing_keys_env_var: str = Field(default="DOWNLOAD_SIGNING_KEYS")
    download_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)


class RateLimitConfig(BaseModel):
    """Deterministic rate limit configuration for CI environments."""

    namespace: str = Field(default="import-to-sabt-rate")
    requests: int = Field(default=5, ge=1, le=1000)
    window_seconds: int = Field(default=60, ge=1, le=3600)
    penalty_seconds: int = Field(default=120, ge=1, le=3600)


class AppConfig(BaseSettings):
    """Application settings with all security knobs disabled for local dev."""

    model_config = SettingsConfigDict(
        env_prefix="IMPORT_TO_SABT_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    redis: RedisConfig = Field(default_factory=RedisConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    ratelimit: RateLimitConfig = Field(default_factory=RateLimitConfig)
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
    def from_env(cls) -> AppConfig:
        """Load configuration from environment variables deterministically."""

        return cls()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig.from_env()


__all__ = [
    "AppConfig",
    "DatabaseConfig",
    "ObservabilityConfig",
    "AuthConfig",
    "RateLimitConfig",
    "RedisConfig",
    "get_config",
]
