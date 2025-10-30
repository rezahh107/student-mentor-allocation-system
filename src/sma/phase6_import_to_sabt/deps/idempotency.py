"""Idempotency header validation helpers."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header, HTTPException

_ZW_RE = re.compile(r"[\u200B-\u200D\uFEFF]")


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None
) -> str:
    """Validate the Idempotency-Key header for POST job requests."""

    if idempotency_key is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "ارسال کلید ایدمپوتنسی الزامی است.",
            },
        )
    key = _ZW_RE.sub("", idempotency_key).strip()
    if not key:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "ارسال کلید ایدمپوتنسی الزامی است.",
            },
        )
    if len(key) > 128:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "طول کلید ایدمپوتنسی نامعتبر است.",
            },
        )
    return key
