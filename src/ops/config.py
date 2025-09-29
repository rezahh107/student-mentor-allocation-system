from __future__ import annotations

"""Configuration objects for ops reporting layer."""

from functools import lru_cache
from typing import Dict

from pydantic import BaseModel, Field, PostgresDsn, field_validator
from pydantic.config import ConfigDict
from pydantic_settings import BaseSettings
from zoneinfo import ZoneInfo


class SLOThresholds(BaseModel):
    """Typed configuration for SLO values used across dashboards."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    healthz_p95_ms: int = Field(..., ge=1, le=1_000)
    readyz_p95_ms: int = Field(..., ge=1, le=1_000)
    export_p95_ms: int = Field(..., ge=1, le=5_000)
    export_error_budget: int = Field(..., ge=1)


class OpsSettings(BaseSettings):
    """Application level settings for ops dashboards."""

    model_config = ConfigDict(env_file=".env", extra="forbid", populate_by_name=True)

    reporting_replica_dsn: PostgresDsn = Field(..., alias="REPORTING_REPLICA_DSN")
    metrics_read_token: str = Field(..., min_length=16, alias="METRICS_READ_TOKEN")
    slo_thresholds: SLOThresholds
    timezone: str = Field("Asia/Baku", alias="OPS_TIMEZONE")

    @field_validator("metrics_read_token")
    @classmethod
    def _ensure_token_format(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("توکن دسترسی نباید فاصلهٔ ابتدایی یا انتهایی داشته باشد")
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:  # pragma: no cover - defensive branch
            raise ValueError("ناحیهٔ زمانی پشتیبانی نمی‌شود") from exc
        return value


@lru_cache(maxsize=1)
def get_settings(**overrides: Dict[str, object]) -> OpsSettings:
    """Return cached settings object with optional overrides for tests."""

    if overrides:
        return OpsSettings(**overrides)
    return OpsSettings()


__all__ = ["OpsSettings", "SLOThresholds", "get_settings"]
