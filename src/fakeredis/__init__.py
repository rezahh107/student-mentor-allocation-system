"""Expose the bundled fakeredis shim when the package is unavailable."""

from __future__ import annotations

import sys
from types import ModuleType

import sma._local_fakeredis as _shim

_module: ModuleType = sys.modules.setdefault(__name__, ModuleType(__name__))

for attribute in ("__file__", "__spec__", "__loader__", "__package__"):
    if hasattr(_shim, attribute):
        setattr(_module, attribute, getattr(_shim, attribute))

for name, value in _shim.__dict__.items():
    if name == "__name__":
        continue
    setattr(_module, name, value)

__all__ = getattr(_shim, "__all__", [])
