from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from zoneinfo import ZoneInfo

ZERO_WIDTH_RE = re.compile("[\u200b-\u200d\u202a-\u202e\ufeff\u2060]")
FA_AR_DIGIT_MAP = str.maketrans({**{chr(0x06F0 + i): str(i) for i in range(10)}, **{chr(0x0660 + i): str(i) for i in range(10)}})


def _normalise_string(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = ZERO_WIDTH_RE.sub("", value).translate(FA_AR_DIGIT_MAP).strip()
        return cleaned
    return value


class RedisConfig(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    dsn: str = Field(min_length=1)
    namespace: str = Field(default="reliability")

    @field_validator("dsn", "namespace", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return _normalise_string(value)


class PostgresConfig(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    read_write_dsn: str = Field(min_length=1)
    replica_dsn: str = Field(min_length=1)

    @field_validator("read_write_dsn", "replica_dsn", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return _normalise_string(value)


class RetentionConfig(BaseModel):
    age_days: int = Field(ge=0)
    max_total_bytes: int = Field(ge=0)


class CleanupConfig(BaseModel):
    part_max_age: int = Field(ge=0, description="Maximum age in seconds for .part files")
    link_ttl: int = Field(ge=0, description="TTL in seconds for signed URLs")


class TokenConfig(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    metrics_read: str = Field(min_length=8)

    @field_validator("metrics_read", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return _normalise_string(value)


class IdempotencyConfig(BaseModel):
    ttl_seconds: int = Field(ge=0, default=24 * 3600)
    storage_prefix: str = Field(default="idem")


class RateLimitRuleModel(BaseModel):
    requests: int = Field(gt=0)
    window_seconds: float = Field(gt=0)


class RateLimitConfigModel(BaseModel):
    model_config = SettingsConfigDict(extra="forbid")

    default_rule: RateLimitRuleModel
    fail_open: bool = False


class ReliabilitySettings(BaseSettings):
    """Typed settings for reliability and disaster recovery tooling."""

    model_config = SettingsConfigDict(extra="forbid")

    redis: RedisConfig
    postgres: PostgresConfig
    artifacts_root: Path
    backups_root: Path
    retention: RetentionConfig
    cleanup: CleanupConfig
    tokens: TokenConfig
    timezone: str = Field(default="Asia/Baku")
    rate_limit: RateLimitConfigModel
    idempotency: IdempotencyConfig = Field(default_factory=IdempotencyConfig)

    @field_validator("artifacts_root", "backups_root", mode="before")
    @classmethod
    def _ensure_path(cls, value: str | Path) -> Path:
        if isinstance(value, Path):
            return value
        return Path(value)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        cleaned = _normalise_string(value)
        try:
            ZoneInfo(cleaned)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unknown timezone: {value}") from exc
        return cleaned

    def clock(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def build_clock(self, now_factory: Callable[[], Any] | None = None) -> "Clock":
        from .clock import Clock

        if now_factory is None:
            return Clock(self.clock())
        return Clock(self.clock(), now_factory)


__all__ = ["ReliabilitySettings", "RedisConfig", "PostgresConfig", "RetentionConfig", "CleanupConfig"]
