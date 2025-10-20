"""Backward-compatible shim for schema validation helpers."""

from __future__ import annotations

from .schemas import validate_pytest_report, validate_strict_report

__all__ = ["validate_pytest_report", "validate_strict_report"]
