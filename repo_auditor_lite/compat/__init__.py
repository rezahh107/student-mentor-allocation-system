"""Compatibility helpers for optional third-party dependencies."""

from __future__ import annotations

from .optional import OptionalDependencyError, optional_import

__all__ = ["OptionalDependencyError", "optional_import"]
