"""Dual-mode shim for pytest-asyncio that defers to the real plugin when present."""

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

    def pytest_configure(config):  # pragma: no cover - compatibility no-op
        del config

