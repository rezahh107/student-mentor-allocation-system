"""Dual-mode pytest-timeout shim that activates real plugin when available."""

from __future__ import annotations

import sys
from typing import Final

from _pytest_plugin_loader import load_real_plugin


_CURRENT = sys.modules[__name__]
_REAL = load_real_plugin(__name__, current_module=_CURRENT)

if _REAL is not None:
    for attribute in ("__file__", "__spec__", "__loader__", "__package__"):
        if hasattr(_REAL, attribute):
            setattr(_CURRENT, attribute, getattr(_REAL, attribute))
    _CURRENT.__dict__.update({k: v for k, v in _REAL.__dict__.items() if k not in {"__name__"}})
    STUB_ACTIVE: Final[bool] = False
else:
    STUB_ACTIVE: Final[bool] = True

    def pytest_addoption(parser):  # pragma: no cover - configuration wiring only
        group = parser.getgroup("timeout-stub")
        group.addoption(
            "--timeout",
            dest="timeout",
            action="store",
            default=None,
            help="pytest-timeout stub: option accepted but ignored.",
        )
        group.addoption(
            "--timeout_method",
            dest="timeout_method",
            action="store",
            default="thread",
            help="pytest-timeout stub: option accepted but ignored.",
        )
        group.addoption(
            "--timeout_func_only",
            dest="timeout_func_only",
            action="store_true",
            default=False,
            help="pytest-timeout stub: flag accepted but ignored.",
        )
        parser.addini(
            "timeout",
            "pytest-timeout stub: ini option accepted but ignored.",
            default=None,
        )
        parser.addini(
            "timeout_method",
            "pytest-timeout stub: ini option accepted but ignored.",
            default="thread",
        )
        parser.addini(
            "timeout_func_only",
            "pytest-timeout stub: ini flag accepted but ignored.",
            default=False,
            type="bool",
        )

    def pytest_configure(config):  # pragma: no cover - no-op hook
        del config
