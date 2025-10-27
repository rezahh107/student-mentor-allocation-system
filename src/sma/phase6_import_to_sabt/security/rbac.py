from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping, Sequence

from sma.phase6_import_to_sabt.app.clock import Clock, build_system_clock
from sma.phase6_import_to_sabt.security.config import TokenDefinition

from .jwt import decode_jwt


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
    """Token/JWT authenticator with deterministic hashing for observability."""

    def __init__(
        self,
        tokens: Sequence[TokenDefinition],
        *,
        hash_salt: str = "import-to-sabt",
        jwt_secret: str | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._records = {record.value: record for record in tokens}
        self._metrics_tokens = {record.value for record in tokens if record.metrics_only}
        self._hash_salt = hash_salt.encode("utf-8")
        self._jwt_secret = jwt_secret
        self._clock = clock or build_system_clock("Asia/Tehran")

    def authenticate(self, value: str, *, allow_metrics: bool) -> AuthenticatedActor:
        if not value:
            raise AuthorizationError(
                "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
                reason="token_missing",
            )
        if allow_metrics and value in self._metrics_tokens:
            return AuthenticatedActor(
                token_fingerprint=self._fingerprint(value),
                role="METRICS_RO",
                center_scope=None,
                metrics_only=True,
            )

        record = self._records.get(value)
        if record is not None:
            if record.metrics_only and not allow_metrics:
                raise AuthorizationError(
                    "دسترسی مجاز نیست؛ نقش/حوزهٔ شما این عملیات را پشتیبانی نمی‌کند.",
                    reason="metrics_only",
                )
            return AuthenticatedActor(
                token_fingerprint=self._fingerprint(value),
                role=record.role,
                center_scope=record.center,
                metrics_only=record.metrics_only,
            )

        if self._jwt_secret and "." in value:
            decoded = decode_jwt(value, secret=self._jwt_secret, clock=self._clock)
            return self._actor_from_claims(decoded.payload, token=value)

        raise AuthorizationError(
            "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
            reason="unknown_token",
        )

    def is_metrics_token(self, value: str) -> bool:
        return value in self._metrics_tokens

    def _actor_from_claims(self, payload: Mapping[str, object], *, token: str) -> AuthenticatedActor:
        role_value = payload.get("role")
        center_value = payload.get("center")
        metrics_only = bool(payload.get("metrics_only"))
        if role_value not in {"ADMIN", "MANAGER"}:
            raise AuthorizationError(
                "دسترسی مجاز نیست؛ نقش/حوزهٔ شما این عملیات را پشتیبانی نمی‌کند.",
                reason="role_invalid",
            )
        center_scope: int | None = None
        if role_value == "MANAGER":
            if center_value is None:
                raise AuthorizationError(
                    "دسترسی مجاز نیست؛ نقش/حوزهٔ شما این عملیات را پشتیبانی نمی‌کند.",
                    reason="center_missing",
                )
            try:
                center_scope = int(center_value)
            except (TypeError, ValueError) as exc:
                raise AuthorizationError(
                    "دسترسی مجاز نیست؛ نقش/حوزهٔ شما این عملیات را پشتیبانی نمی‌کند.",
                    reason="center_invalid",
                ) from exc
        fingerprint = self._fingerprint(token)
        return AuthenticatedActor(
            token_fingerprint=fingerprint,
            role=role_value,  # type: ignore[arg-type]
            center_scope=center_scope,
            metrics_only=metrics_only,
        )

    def _fingerprint(self, value: str) -> str:
        digest = hashlib.blake2b(digest_size=10, key=self._hash_salt)
        digest.update(value.encode("utf-8"))
        return digest.hexdigest()

    def tokens(self) -> Iterable[str]:
        return self._records.keys()


def enforce_center_scope(actor: AuthenticatedActor, *, center: int | None) -> None:
    if not actor.can_access_center(center):
        raise AuthorizationError(
            "دسترسی مجاز نیست؛ نقش/حوزهٔ شما این عملیات را پشتیبانی نمی‌کند.",
            reason="scope_denied",
        )


__all__ = [
    "AuthenticatedActor",
    "AuthorizationError",
    "TokenRegistry",
    "enforce_center_scope",
]

