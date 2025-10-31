"""Shared utilities bridging old and new service layers."""

from __future__ import annotations

from .atomic import atomic_output_path, temporary_atomic_path

__all__ = ["atomic_output_path", "temporary_atomic_path"]
