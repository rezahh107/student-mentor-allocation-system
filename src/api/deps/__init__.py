"""Dependency helpers for API routes."""

from .idempotency import require_idempotency_key

__all__ = ["require_idempotency_key"]
