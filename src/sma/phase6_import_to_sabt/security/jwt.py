"""Deterministic JWT helpers for ImportToSabt security flows."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping

from sma.phase6_import_to_sabt.app.clock import Clock


_SUPPORTED_ALG = "HS256"


@dataclass(slots=True)
class DecodedJWT:
    """Structured representation of a decoded JWT payload."""

    subject: str
    payload: Mapping[str, Any]


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def decode_jwt(token: str, *, secret: str, clock: Clock, leeway: int = 60) -> DecodedJWT:
    """Decode and validate a compact JWT signed with HS256.

    Parameters
    ----------
    token:
        Compact JWT value (``header.payload.signature``).
    secret:
        Shared secret used for HS256 verification.
    clock:
        Injected Tehran-aware clock for deterministic validation.
    leeway:
        Maximum tolerance (seconds) applied to ``exp``/``iat`` checks.

    Raises
    ------
    AuthorizationError
        If the token cannot be decoded or violates validation rules.
    """

    from .rbac import AuthorizationError

    parts = token.split(".")
    if len(parts) != 3:
        raise AuthorizationError(
            "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
            reason="jwt_format",
        )

    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64decode(header_b64))
        payload = json.loads(_b64decode(payload_b64))
        signature = _b64decode(signature_b64)
    except (json.JSONDecodeError, ValueError) as exc:  # pragma: no cover - defensive
        raise AuthorizationError(
            "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
            reason="jwt_decode",
        ) from exc

    if header.get("alg") != _SUPPORTED_ALG:
        raise AuthorizationError(
            "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
            reason="jwt_alg",
        )

    signing_input = "".join([header_b64, ".", payload_b64]).encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, signature):
        raise AuthorizationError(
            "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
            reason="jwt_signature",
        )

    now = int(clock.now().timestamp())
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        if now > int(exp) + leeway:
            raise AuthorizationError(
                "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
                reason="jwt_expired",
            )
    iat = payload.get("iat")
    if isinstance(iat, (int, float)):
        if now + leeway < int(iat):
            raise AuthorizationError(
                "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
                reason="jwt_iat",
            )

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthorizationError(
            "درخواست نامعتبر است؛ احراز هویت انجام نشد.",
            reason="jwt_subject",
        )

    return DecodedJWT(subject=subject, payload=payload)


__all__ = ["DecodedJWT", "decode_jwt"]

