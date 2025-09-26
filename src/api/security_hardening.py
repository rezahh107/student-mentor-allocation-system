"""Security helpers used across the hardened API."""
from __future__ import annotations

import hmac
import ipaddress
from typing import Iterable, Mapping

from fastapi import HTTPException, Request, status


def constant_time_compare(left: str, right: str) -> bool:
    """Compare two secrets using ``hmac.compare_digest``."""

    if not left or not right:
        return False
    try:
        return hmac.compare_digest(left, right)
    except Exception:
        return False


def ensure_metrics_authorized(
    request: Request,
    *,
    token: str | None,
    ip_allowlist: Iterable[str] | None,
) -> None:
    """Validate access to the metrics endpoint."""

    client_ip = request.client.host if request.client else ""
    allowed_ips = {normalize_ip(ip) for ip in ip_allowlist or [] if ip}

    if token:
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            raise _unauthorized()
        candidate = header[7:].strip()
        if not constant_time_compare(candidate, token):
            raise _unauthorized()
        if allowed_ips and client_ip and normalize_ip(client_ip) not in allowed_ips:
            raise _forbidden()
        return

    if allowed_ips and client_ip and normalize_ip(client_ip) in allowed_ips:
        return
    raise _forbidden()


def validate_jwt_claims(
    payload: Mapping[str, object],
    *,
    issuer: str | None,
    audience: str | None,
) -> None:
    """Ensure JWT claims satisfy configured expectations."""

    if issuer is not None:
        token_issuer = payload.get("iss")
        if token_issuer != issuer:
            raise ValueError("invalid issuer")
    if audience is not None:
        token_aud = payload.get("aud")
        if isinstance(token_aud, (list, tuple, set)):
            if audience not in token_aud:
                raise ValueError("invalid audience")
        elif token_aud != audience:
            raise ValueError("invalid audience")


def normalize_ip(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        return ip.strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTH_REQUIRED", "message_fa": "توکن دسترسی به متریک نامعتبر است"},
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "ROLE_DENIED", "message_fa": "دسترسی به متریک مجاز نیست"},
    )

