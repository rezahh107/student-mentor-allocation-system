"""Context management helpers for request-scoped debug data."""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.debug.debug_context import DebugContext

_DEBUG_CONTEXT: ContextVar["DebugContext | None"] = ContextVar(
    "debug_context", default=None
)


def set_debug_context(ctx: "DebugContext | None") -> Token["DebugContext | None"]:
    """Bind the provided debug context to the current execution context."""

    return _DEBUG_CONTEXT.set(ctx)


def reset_debug_context(token: Token["DebugContext | None"]) -> None:
    """Restore the debug context to a previous state."""

    _DEBUG_CONTEXT.reset(token)


def get_debug_context() -> "DebugContext | None":
    """Return the currently bound debug context, if any."""

    return _DEBUG_CONTEXT.get()


__all__ = ["set_debug_context", "reset_debug_context", "get_debug_context"]
