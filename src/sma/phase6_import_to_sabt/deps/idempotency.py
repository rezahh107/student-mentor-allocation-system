"""Development-friendly idempotency helpers (no validation)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """Return the provided header without enforcing any validation."""

    return idempotency_key


__all__ = ["require_idempotency_key"]
