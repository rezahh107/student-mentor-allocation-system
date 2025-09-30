from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AuthError(Exception):
    code: str
    message_fa: str
    reason: str

    def __str__(self) -> str:  # pragma: no cover - representational
        return f"{self.code}: {self.message_fa}"  # type: ignore[str-format]


class ConfigError(AuthError):
    pass


class ProviderError(AuthError):
    pass


__all__ = ["AuthError", "ConfigError", "ProviderError"]
