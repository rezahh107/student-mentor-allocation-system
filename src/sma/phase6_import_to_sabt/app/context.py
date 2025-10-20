"""Request-scoped context helpers for ImportToSabt services."""

from __future__ import annotations

from contextvars import ContextVar, Token


_CORRELATION_ID: ContextVar[str] = ContextVar("phase6_correlation_id", default="unknown")


def set_correlation_id(value: str) -> Token[str]:
    """Bind *value* as the active correlation identifier for the current task."""

    return _CORRELATION_ID.set(value)


def reset_correlation_id(token: Token[str]) -> None:
    """Restore the correlation identifier to the state captured by *token*."""

    _CORRELATION_ID.reset(token)


def get_current_correlation_id() -> str:
    """Return the correlation identifier associated with the current execution context."""

    return _CORRELATION_ID.get()


__all__ = ["set_correlation_id", "reset_correlation_id", "get_current_correlation_id"]
