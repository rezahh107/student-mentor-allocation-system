"""Shared exception types for Windows service integration."""

from __future__ import annotations

from typing import Mapping


class ServiceError(RuntimeError):
    """Raised when service orchestration encounters a recoverable error."""

    __slots__ = ("code", "message", "context")

    def __init__(self, code: str, message: str, *, context: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})


class DependencyNotReady(ServiceError):
    """Raised when an external dependency is not ready for service startup."""

    def __init__(self, message: str, *, context: Mapping[str, str] | None = None) -> None:
        super().__init__("DEPENDENCY_NOT_READY", message, context=context)
