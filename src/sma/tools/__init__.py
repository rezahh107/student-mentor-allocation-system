"""Headless-safe tool shims for CI environments.

This package exposes the public surface expected by tests while
preferring lightweight implementations that remain deterministic under
headless CI runners. Native GUI bindings can still be enabled via
``SMA_GUI_NATIVE=1`` for local smoke tests without affecting CI.
"""
from __future__ import annotations

import os

if os.environ.get("SMA_GUI_NATIVE", "0") == "1":  # pragma: no cover - opt-in path
    from sma._local_tools.gui_operator import (  # type: ignore[F401]
        HEADLESS_DIAGNOSTIC,
        OperatorGUI,
    )
else:  # default CI/headless mode
    from .gui_operator import HEADLESS_DIAGNOSTIC, OperatorGUI  # noqa: F401

__all__ = ["OperatorGUI", "HEADLESS_DIAGNOSTIC"]
