from __future__ import annotations

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone


def _b64encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


def build_jwt(
    *,
    secret: str,
    subject: str,
    role: str,
    center: int | None = None,
    metrics_only: bool = False,
    iat: int | None = None,
    exp: int | None = None,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(datetime.now(tz=timezone.utc).timestamp())
    payload: dict[str, object] = {
        "sub": subject,
        "role": role,
        "center": center,
        "metrics_only": metrics_only,
        "iat": iat if iat is not None else now,
        "exp": exp if exp is not None else now + 3600,
    }
    header_part = _b64encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_part = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_part = _b64encode(signature)
    return f"{header_part}.{payload_part}.{signature_part}"


__all__ = ["build_jwt"]

