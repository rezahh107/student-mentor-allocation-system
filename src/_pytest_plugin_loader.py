"""Expose the local plugin loader when pytest tries to import it globally."""

from __future__ import annotations

import sys
from types import ModuleType

import sma._pytest_plugin_loader as _loader

_module: ModuleType = sys.modules.setdefault(__name__, ModuleType(__name__))

for attribute in ("__file__", "__spec__", "__loader__", "__package__"):
    if hasattr(_loader, attribute):
        setattr(_module, attribute, getattr(_loader, attribute))

for name, value in _loader.__dict__.items():
    if name == "__name__":
        continue
    setattr(_module, name, value)

__all__ = getattr(_loader, "__all__", [])
