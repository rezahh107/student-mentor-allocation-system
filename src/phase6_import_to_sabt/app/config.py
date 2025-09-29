from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    model_config = SettingsConfigDict(env_prefix="IMPORT_TO_SABT_", extra="forbid")

    redis: RedisConfig
    database: DatabaseConfig
    auth: AuthConfig
    ratelimit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    timezone: str = Field(default="Asia/Baku")
    readiness_timeout_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    health_timeout_seconds: float = Field(default=0.2, ge=0.1, le=5.0)
    enable_debug_logs: bool = Field(default=False)
    enable_diagnostics: bool = Field(default=False)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig()  # type: ignore[call-arg]


__all__ = [
    "AppConfig",
    "AuthConfig",
    "DatabaseConfig",
    "ObservabilityConfig",
    "RateLimitConfig",
    "RedisConfig",
    "get_config",
]
