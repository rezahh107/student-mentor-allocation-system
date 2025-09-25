"""Shim برای سازگاری PluginValidationError در درگاه پوشش."""
from __future__ import annotations


class _FallbackPluginValidationError(Exception):
    """جایگزین محلی در صورت نبود pytest."""


try:  # pragma: no cover - مسیر اصلی در محیط‌های دارای pytest
    from _pytest.config.exceptions import PluginValidationError as _PluginValidationError  # type: ignore
except Exception:  # pragma: no cover - در تست‌های بدون pytest فعال می‌شود
    PluginValidationError = _FallbackPluginValidationError
else:  # pragma: no cover - فراگیری برای سازگاری type checker
    PluginValidationError = _PluginValidationError


__all__ = ["PluginValidationError"]
