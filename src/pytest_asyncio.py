"""Compatibility shim exposing the local pytest-asyncio stub as ``pytest_asyncio``."""

from __future__ import annotations

import sys
from types import ModuleType

import sma._local_pytest_asyncio as _shim

_module: ModuleType = sys.modules.setdefault(__name__, ModuleType(__name__))

for attribute in ("__file__", "__spec__", "__loader__", "__package__", "__path__"):
    if hasattr(_shim, attribute):
        setattr(_module, attribute, getattr(_shim, attribute))

for name, value in _shim.__dict__.items():
    if name == "__name__":
        continue
    setattr(_module, name, value)

_shim_exports = getattr(_shim, "__all__", [])
if isinstance(_shim_exports, list | tuple):
    __all__ = tuple(_shim_exports)
else:
    __all__ = tuple(
        sorted(name for name in _shim.__dict__ if not name.startswith("__"))
    )
