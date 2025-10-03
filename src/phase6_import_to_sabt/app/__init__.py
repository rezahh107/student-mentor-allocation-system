"""ImportToSabt Phase 1 FastAPI application package."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "create_application": "phase6_import_to_sabt.app.app_factory:create_application",
    "create_app": "phase6_import_to_sabt.app.app_factory:create_application",
    "build_app": "phase6_import_to_sabt.app.app_factory:create_application",
    "ApplicationContainer": "phase6_import_to_sabt.app.app_factory:ApplicationContainer",
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if not target:
        raise AttributeError(name)
    module_name, attr = target.split(":")
    module = import_module(module_name)
    value = getattr(module, attr)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS.keys())
