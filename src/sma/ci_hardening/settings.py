"""Typed settings management with deterministic Persian failures."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MANDATORY_SECTIONS = ("redis", "database", "auth")


class SettingsError(ValueError):
    """Raised when configuration is incomplete or invalid."""


class RedisSettings(BaseModel):
    """Configuration for Redis connectivity."""

    host: str = Field(..., description="Redis hostname", examples=["localhost"])
    port: int = Field(..., description="Redis port", ge=0, le=65535, examples=[6379])
    db: int = Field(default=0, ge=0, description="Database index")
    namespace: str = Field(default="sma-ci", description="Namespace prefix for keys")


class DatabaseSettings(BaseModel):
    """Database connection settings."""

    dsn: str = Field(..., description="SQLAlchemy-compatible DSN")


class AuthSettings(BaseModel):
    """Authentication tokens used by middleware."""

    service_token: str = Field(..., min_length=8)
    metrics_token: str | None = Field(default=None, min_length=8)


class ObservabilitySettings(BaseModel):
    """Observability toggles."""

    metrics_namespace: str = Field(default="sma_ci")
    enable_metrics: bool = Field(default=True)


class RetrySettings(BaseModel):
    """Retry/backoff policy configuration."""

    max_attempts: int = Field(default=3, ge=1)
    base_delay_seconds: float = Field(default=0.1, ge=0.0)


class AppSettings(BaseSettings):
    """Aggregate settings for deterministic application boot."""

    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    @model_validator(mode="before")
    @classmethod
    def _validate_sections(cls, values: Any) -> Any:
        data = dict(values or {})
        missing = [section for section in _MANDATORY_SECTIONS if not data.get(section)]
        if missing:
            raise SettingsError(
                "پیکربندی ناقص است؛ بخش‌های redis/database/auth الزامی است."
            )
        return values

    redis: RedisSettings
    database: DatabaseSettings
    auth: AuthSettings
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    timezone: str = Field(default="Asia/Tehran")

    @model_validator(mode="after")
    def _ensure_sections(self) -> "AppSettings":
        missing = [
            section
            for section in _MANDATORY_SECTIONS
            if getattr(self, section, None) is None
        ]
        if missing:
            raise SettingsError(
                "پیکربندی ناقص است؛ بخش‌های redis/database/auth الزامی است."
            )
        return self

    def as_safe_dict(self) -> Dict[str, Any]:
        """Return a dictionary representation without exposing secret values."""

        masked = {
            "redis": self.redis.model_dump(),
            "database": {"dsn": "***"},
            "auth": {"service_token": "***", "metrics_token": "***"},
            "observability": self.observability.model_dump(),
            "retry": self.retry.model_dump(),
            "timezone": self.timezone,
        }
        return masked

    @classmethod
    def load(cls) -> "AppSettings":
        """Load settings from environment and ``.env`` file."""

        try:
            return cls()  # type: ignore[call-arg]
        except (ValidationError, SettingsError) as exc:  # pragma: no cover - fatal path
            raise SettingsError(
                "پیکربندی ناقص است؛ بخش‌های redis/database/auth الزامی است."
            ) from exc


@dataclass(frozen=True)
class ExampleValue:
    """Simple container to describe example variables."""

    key: str
    value: str
    comment: str

    def render(self) -> str:
        """Render the example entry with deterministic comments."""

        return f"{self.comment}\n{self.key}={self.value}\n"


def _example_entries() -> tuple[ExampleValue, ...]:
    return (
        ExampleValue("REDIS__HOST", "localhost", "# Redis configuration"),
        ExampleValue("REDIS__PORT", "6379", "# پورت Redis"),
        ExampleValue("REDIS__DB", "0", "# شماره پایگاه داده"),
        ExampleValue("REDIS__NAMESPACE", "sma-ci", "# پیشوند نام‌ها"),
        ExampleValue(
            "DATABASE__DSN",
            "postgresql+psycopg://user:pass@localhost:5432/app",
            "# اتصال پایگاه داده",
        ),
        ExampleValue("AUTH__SERVICE_TOKEN", "super-secret-token", "# توکن سرویس"),
        ExampleValue("AUTH__METRICS_TOKEN", "metrics-token", "# توکن متریک"),
        ExampleValue("OBSERVABILITY__METRICS_NAMESPACE", "sma_ci", "# فضای نام متریک"),
        ExampleValue("RETRY__MAX_ATTEMPTS", "3", "# حداکثر تلاش"),
        ExampleValue("RETRY__BASE_DELAY_SECONDS", "0.1", "# تأخیر پایه"),
        ExampleValue("TIMEZONE", "Asia/Tehran", "# منطقهٔ زمانی"),
    )


def _part_path(target: Path) -> Path:
    suffix = f"{target.suffix}.part" if target.suffix else ".part"
    if suffix == ".part":
        return target.with_name(f"{target.name}.part")
    return target.with_suffix(suffix)


def generate_env_example(path: str | Path = ".env.example") -> Path:
    """Generate a deterministic ``.env.example`` file."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(entry.render() for entry in _example_entries())
    if not content.endswith("\n"):
        content = f"{content}\n"
    part_path = _part_path(target)
    with part_path.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    part_path.replace(target)
    return target


__all__ = [
    "AppSettings",
    "AuthSettings",
    "DatabaseSettings",
    "ExampleValue",
    "RedisSettings",
    "RetrySettings",
    "SettingsError",
    "generate_env_example",
]
