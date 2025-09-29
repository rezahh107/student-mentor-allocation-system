from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{16,256}$")
KID_PATTERN = re.compile(r"^[A-Za-z0-9]{4,32}$")
SECRET_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{32,512}$")

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
_ZERO_WIDTH = {"\u200c", "\u200d", "\ufeff", "\u2060"}


class ConfigGuardError(ValueError):
    """Raised when access configuration is invalid."""


@dataclass(frozen=True)
class TokenDefinition:
    value: str
    role: Literal["ADMIN", "MANAGER", "METRICS_RO"]
    center: int | None
    metrics_only: bool


@dataclass(frozen=True)
class SigningKeyDefinition:
    kid: str
    secret: str
    state: Literal["active", "next", "retired"]


@dataclass(frozen=True)
class AccessSettings:
    tokens: tuple[TokenDefinition, ...]
    signing_keys: tuple[SigningKeyDefinition, ...]
    metrics_tokens: tuple[str, ...]
    active_kid: str
    next_kid: str | None
    download_ttl_seconds: int


def _normalize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        text = str(value)
    else:
        text = str(value)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_DIGIT_TRANSLATION)
    for marker in _ZERO_WIDTH:
        text = text.replace(marker, "")
    return text.strip()


class _TokenModel(BaseModel):
    value: str = Field(...)
    role: Literal["ADMIN", "MANAGER", "METRICS_RO"]
    center: int | None = None
    metrics_only: bool = Field(
        default=False,
        validation_alias=AliasChoices("metrics_only", "metrics"),
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("value", mode="before")
    @classmethod
    def _normalize_value(cls, value: Any) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("token-empty")
        if not TOKEN_PATTERN.fullmatch(normalized):
            raise ValueError("token-format")
        return normalized

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: Any) -> str:
        normalized = _normalize(value).upper()
        if normalized not in {"ADMIN", "MANAGER", "METRICS_RO"}:
            raise ValueError("role-invalid")
        return normalized

    @field_validator("center", mode="before")
    @classmethod
    def _normalize_center(cls, value: Any) -> int | None:
        normalized = _normalize(value)
        if not normalized:
            return None
        if not normalized.isdigit():
            raise ValueError("center-format")
        number = int(normalized)
        if number <= 0:
            raise ValueError("center-range")
        return number

    @model_validator(mode="after")
    def _validate_scope(self) -> "_TokenModel":
        metrics_flag = bool(self.metrics_only)
        if self.role == "MANAGER" and self.center is None:
            raise ValueError("center-required")
        if self.role == "METRICS_RO":
            if self.center is not None:
                raise ValueError("metrics-center-not-allowed")
            metrics_flag = True
        if metrics_flag and self.role != "METRICS_RO":
            raise ValueError("metrics-role-required")
        self.metrics_only = metrics_flag
        return self


class _SigningKeyModel(BaseModel):
    kid: str = Field(...)
    secret: str = Field(...)
    state: Literal["active", "next", "retired"] = "active"

    model_config = ConfigDict(extra="forbid")

    @field_validator("kid", mode="before")
    @classmethod
    def _normalize_kid(cls, value: Any) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("kid-empty")
        if not KID_PATTERN.fullmatch(normalized):
            raise ValueError("kid-format")
        return normalized

    @field_validator("secret", mode="before")
    @classmethod
    def _normalize_secret(cls, value: Any) -> str:
        normalized = _normalize(value)
        if not normalized:
            raise ValueError("secret-empty")
        if not SECRET_PATTERN.fullmatch(normalized):
            raise ValueError("secret-format")
        return normalized


class AccessConfigGuard:
    """Validate runtime access configuration with deterministic Persian errors."""

    def __init__(self, *, env: Mapping[str, str] | None = None) -> None:
        self._env = dict(env or os.environ)

    def load(
        self,
        *,
        tokens_env: str = "TOKENS",
        signing_keys_env: str = "DOWNLOAD_SIGNING_KEYS",
        download_ttl_seconds: int = 900,
    ) -> AccessSettings:
        tokens_payload = self._decode_json(tokens_env)
        keys_payload = self._decode_json(signing_keys_env)
        tokens = self._parse_tokens(tokens_payload)
        signing_keys = self._parse_keys(keys_payload)

        if not signing_keys:
            raise ConfigGuardError("«پیکربندی نامعتبر است؛ کلید امضای دانلود تعریف نشده است.»")

        active_keys = [key for key in signing_keys if key.state == "active"]
        if len(active_keys) != 1:
            raise ConfigGuardError("«پیکربندی نامعتبر است؛ دقیقاً یک کلید فعال لازم است.»")

        next_keys = [key for key in signing_keys if key.state == "next"]
        if len(next_keys) > 1:
            raise ConfigGuardError("«پیکربندی نامعتبر است؛ فقط یک کلید بعدی مجاز است.»")

        if download_ttl_seconds <= 0:
            raise ConfigGuardError("«پیکربندی نامعتبر است؛ مدت اعتبار لینک باید مثبت باشد.»")

        metrics_tokens = tuple(record.value for record in tokens if record.metrics_only)

        return AccessSettings(
            tokens=tuple(tokens),
            signing_keys=tuple(signing_keys),
            metrics_tokens=metrics_tokens,
            active_kid=active_keys[0].kid,
            next_kid=next_keys[0].kid if next_keys else None,
            download_ttl_seconds=download_ttl_seconds,
        )

    def _decode_json(self, name: str) -> Any:
        raw = self._env.get(name, "[]")
        text = _normalize(raw)
        if not text:
            return []
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:  # pragma: no cover - deterministic failure path
            raise ConfigGuardError(
                f"«پیکربندی نامعتبر است؛ مقدار JSON برای {name} قابل خواندن نیست.»"
            ) from exc

    def _parse_tokens(self, payload: Any) -> list[TokenDefinition]:
        if payload in (None, ""):
            return []
        if not isinstance(payload, Iterable):
            raise ConfigGuardError("«پیکربندی نامعتبر است؛ فهرست توکن‌ها معتبر نیست.»")
        records: list[TokenDefinition] = []
        seen: set[str] = set()
        for idx, item in enumerate(payload):
            try:
                model = _TokenModel.model_validate(item)
            except ValidationError as exc:  # pragma: no cover - triggered via tests
                raise ConfigGuardError(_to_persian_error("token", idx, exc)) from exc
            if model.value in seen:
                raise ConfigGuardError("«پیکربندی نامعتبر است؛ توکن تکراری تعریف شده است.»")
            seen.add(model.value)
            records.append(
                TokenDefinition(
                    model.value,
                    model.role,
                    model.center,
                    model.metrics_only,
                )
            )
        return records

    def _parse_keys(self, payload: Any) -> list[SigningKeyDefinition]:
        if payload in (None, ""):
            return []
        if not isinstance(payload, Iterable):
            raise ConfigGuardError("«پیکربندی نامعتبر است؛ فهرست کلیدهای دانلود معتبر نیست.»")
        records: list[SigningKeyDefinition] = []
        seen: set[str] = set()
        for idx, item in enumerate(payload):
            try:
                model = _SigningKeyModel.model_validate(item)
            except ValidationError as exc:  # pragma: no cover - triggered via tests
                raise ConfigGuardError(_to_persian_error("key", idx, exc)) from exc
            if model.kid in seen:
                raise ConfigGuardError("«پیکربندی نامعتبر است؛ شناسه کلید تکراری است.»")
            seen.add(model.kid)
            records.append(SigningKeyDefinition(model.kid, model.secret, model.state))
        return records


def _to_persian_error(kind: str, index: int, exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "«پیکربندی نامعتبر است؛ مقدار ناشناخته.»"
    detail = errors[0]
    location = detail.get("loc", ("?",))
    field = location[-1] if isinstance(location, (list, tuple)) else location
    code = detail.get("msg", "invalid")
    if detail.get("type") in {"value_error.extra", "extra_forbidden"}:
        return f"«پیکربندی نامعتبر است؛ کلید ناشناخته برای {kind}[{index}]: {field}»"
    if code in {"token-empty", "kid-empty", "secret-empty"}:
        return "«پیکربندی نامعتبر است؛ مقدار الزامی خالی است.»"
    if code in {"token-format", "secret-format"}:
        return "«پیکربندی نامعتبر است؛ مقدار توکن با الگو سازگار نیست.»"
    if code == "role-invalid":
        return "«پیکربندی نامعتبر است؛ نقش نامعتبر است.»"
    if code in {"center-format", "center-range", "center-required"}:
        return "«پیکربندی نامعتبر است؛ شناسه مرکز نامعتبر است.»"
    if code == "kid-format":
        return "«پیکربندی نامعتبر است؛ شناسه کلید نامعتبر است.»"
    if code == "metrics-center-not-allowed":
        return "«پیکربندی نامعتبر است؛ مرکز برای توکن متریک مجاز نیست.»"
    if code == "metrics-role-required":
        return "«پیکربندی نامعتبر است؛ نقش METRICS_RO برای توکن متریک الزامی است.»"
    return f"«پیکربندی نامعتبر است؛ مقدار نامعتبر برای {kind}[{index}]»"


__all__ = [
    "AccessConfigGuard",
    "AccessSettings",
    "ConfigGuardError",
    "SigningKeyDefinition",
    "TokenDefinition",
]

