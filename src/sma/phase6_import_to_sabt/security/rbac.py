from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from sma.phase6_import_to_sabt.security.config import TokenDefinition


class AuthorizationError(Exception):
    """Raised when RBAC rules reject the current request."""

    def __init__(self, message_fa: str, *, reason: str) -> None:
        super().__init__(message_fa)
        self.message_fa = message_fa
        self.reason = reason


@dataclass(frozen=True)
class AuthenticatedActor:
    token_fingerprint: str
    role: Literal["ADMIN", "MANAGER", "METRICS_RO"]
    center_scope: int | None
    metrics_only: bool

    def can_access_center(self, center: int | None) -> bool:
        if self.role == "ADMIN":
            return True
        if center is None:
            return False
        return self.center_scope == center


class TokenRegistry:
    """Constant-time token lookup with deterministic hashing for logs."""

    def __init__(self, tokens: Sequence[TokenDefinition], *, hash_salt: str = "import-to-sabt") -> None:
        self._records = {record.value: record for record in tokens}
        self._metrics_tokens = {record.value for record in tokens if record.metrics_only}
        self._hash_salt = hash_salt.encode("utf-8")

    def authenticate(self, value: str, *, allow_metrics: bool) -> AuthenticatedActor:
        record = self._records.get(value)
        if record is None:
            raise AuthorizationError("توکن نامعتبر است.", reason="unknown_token")
        if record.metrics_only and not allow_metrics:
            raise AuthorizationError("توکن نامعتبر است.", reason="metrics_only")
        fingerprint = self._fingerprint(value)
        return AuthenticatedActor(
            token_fingerprint=fingerprint,
            role=record.role,
            center_scope=record.center,
            metrics_only=record.metrics_only,
        )

    def is_metrics_token(self, value: str) -> bool:
        return value in self._metrics_tokens

    def _fingerprint(self, value: str) -> str:
        digest = hashlib.blake2b(digest_size=10, key=self._hash_salt)
        digest.update(value.encode("utf-8"))
        return digest.hexdigest()

    def tokens(self) -> Iterable[str]:
        return self._records.keys()


def enforce_center_scope(actor: AuthenticatedActor, *, center: int | None) -> None:
    if not actor.can_access_center(center):
        raise AuthorizationError("دسترسی شما برای این مرکز مجاز نیست.", reason="scope_denied")


__all__ = [
    "AuthenticatedActor",
    "AuthorizationError",
    "TokenRegistry",
    "enforce_center_scope",
]

