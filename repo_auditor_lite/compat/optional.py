"""Lazy optional dependency loader with deterministic Persian fallbacks."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Dict

__all__ = ["OptionalDependencyError", "optional_import"]

_OPTIONAL_NAMES = {
    "requests",
    "yaml",
    "sqlalchemy",
    "httpx",
    "xlsxwriter",
}


class OptionalDependencyError(RuntimeError):
    """Raised when a missing optional dependency is accessed at runtime."""

    def __init__(self, module_name: str, attribute: str | None = None) -> None:
        attribute_hint = f" (ویژگی {attribute})" if attribute else ""
        message = (
            f"کتابخانهٔ اختیاری {module_name} در دسترس نیست{attribute_hint}; "
            "لطفاً بسته را نصب کرده یا قابلیت وابسته را غیرفعال کنید."
        )
        super().__init__(message)
        self.module_name = module_name
        self.attribute = attribute


class _ShimModule(ModuleType):
    """Module shim that defers the Persian error until attribute access."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__dict__["__doc__"] = (
            "Shim module for optional dependency; accessing attributes raises a Persian error."
        )

    def __getattr__(self, item: str):  # type: ignore[override]
        raise OptionalDependencyError(self.__name__, item)


_SHIM_CACHE: Dict[str, ModuleType] = {}


def _shim_for(name: str) -> ModuleType:
    module = _SHIM_CACHE.get(name)
    if module is None:
        module = _ShimModule(name)
        _SHIM_CACHE[name] = module
    return module


def optional_import(name: str) -> ModuleType:
    """Return the requested optional module or a deterministic shim."""

    if name not in _OPTIONAL_NAMES:
        return importlib.import_module(name)
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError:
        module = _shim_for(name)
    return module
