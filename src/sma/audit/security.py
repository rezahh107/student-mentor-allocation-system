"""Audit download signed URL utilities."""
from __future__ import annotations

import base64
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Protocol

from sma.core.clock import SupportsNow, tehran_clock


class SignedURLVerifier(Protocol):
    """Minimal protocol for signing and verifying download URLs."""

    def sign(self, resource: str, *, expires_in: int | None = None) -> str:
        ...

    def verify(self, resource: str, token: str, *, now: datetime | None = None) -> bool:
        ...


def _utc_timestamp(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())


@dataclass(slots=True)
class AuditSignedURLProvider:
    """Generate short-lived HMAC tokens for audit exports."""

    secret: bytes
    clock: Callable[[], datetime]
    default_ttl: int = 300

    def __init__(
        self,
        secret: str | bytes,
        *,
        clock: SupportsNow | Callable[[], datetime] | None = None,
        default_ttl: int = 300,
    ) -> None:
        self.secret = secret if isinstance(secret, bytes) else secret.encode("utf-8")
        if clock is None:
            self.clock = tehran_clock().now
        elif hasattr(clock, "now"):
            self.clock = getattr(clock, "now")  # type: ignore[assignment]
        else:
            self.clock = clock
        self.default_ttl = default_ttl

    def sign(self, resource: str, *, expires_in: int | None = None) -> str:
        ttl = self.default_ttl if expires_in is None else max(1, int(expires_in))
        issued_at = _utc_timestamp(self.clock())
        expires_at = issued_at + ttl
        nonce = base64.urlsafe_b64encode(os.urandom(12)).decode("ascii").rstrip("=")
        payload = f"{resource}|{issued_at}|{expires_at}|{nonce}".encode("utf-8")
        digest = hmac.new(self.secret, payload, sha256).hexdigest()
        token = base64.urlsafe_b64encode(f"{issued_at}:{expires_at}:{nonce}:{digest}".encode("utf-8")).decode("ascii")
        return token.rstrip("=")

    def verify(self, resource: str, token: str, *, now: datetime | None = None) -> bool:
        if not token:
            return False
        padding = "=" * (-len(token) % 4)
        try:
            decoded = base64.urlsafe_b64decode(token + padding).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        parts = decoded.split(":")
        if len(parts) != 4:
            return False
        issued_raw, expires_raw, nonce, digest = parts
        try:
            issued_at = int(issued_raw)
            expires_at = int(expires_raw)
        except ValueError:
            return False
        current = _utc_timestamp(now or self.clock())
        if current < issued_at or current > expires_at:
            return False
        payload = f"{resource}|{issued_raw}|{expires_raw}|{nonce}".encode("utf-8")
        expected = hmac.new(self.secret, payload, sha256).hexdigest()
        return hmac.compare_digest(expected, digest)


__all__ = ["AuditSignedURLProvider", "SignedURLVerifier"]
