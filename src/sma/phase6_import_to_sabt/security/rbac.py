"""Simplified RBAC stubs for local development.

All authentication and authorization logic has been removed intentionally.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


class AuthorizationError(Exception):
    """Placeholder exception kept for compatibility."""

    def __init__(self, message_fa: str, *, reason: str | None = None) -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.reason = reason or "disabled"


@dataclass(slots=True)
class AuthenticatedActor:
    """Stub data container preserved for legacy call sites."""

    token_fingerprint: str = "dev-token"
    role: Literal["ADMIN", "MANAGER", "METRICS_RO"] = "ADMIN"
    center_scope: int | None = None
    metrics_only: bool = False

    def can_access_center(self, center: int | None) -> bool:
        """Always grant access in the simplified environment."""

        return True


class TokenRegistry:
    """No-op token registry kept for constructor compatibility."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - simple stub
        pass

    def authenticate(self, value: str, *, allow_metrics: bool = True) -> AuthenticatedActor:
        """Return an administrative actor without validating the token."""

        return AuthenticatedActor()

    def tokens(self) -> Iterable[str]:
        """Return an empty token list."""

        return []

    def is_metrics_token(self, value: str) -> bool:
        """Always report that the value is not a metrics-only token."""

        return False


def enforce_center_scope(actor: AuthenticatedActor, *, center: int | None) -> None:
    """No-op scope enforcement for local development."""

    return None


__all__ = [
    "AuthenticatedActor",
    "AuthorizationError",
    "TokenRegistry",
    "enforce_center_scope",
]
