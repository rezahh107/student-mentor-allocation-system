"""Utilities for running UI tests in headless environments."""
from __future__ import annotations

import ctypes
import ctypes.util
import os
from typing import Final

import pytest

_SKIP_REASON: Final = "محیط هدلس: کتابخانه‌های PySide6 یا libGL در دسترس نیست."


def _probe_pyside6() -> bool:
    """Return ``True`` when PySide6 can be imported safely."""

    try:
        import PySide6  # noqa: F401  # pylint: disable=unused-import
    except Exception:  # noqa: BLE001 - broad to cover missing shared libs
        return False
    return True


def _probe_libgl() -> bool:
    """Return ``True`` when an OpenGL shared library is available."""

    library_name = ctypes.util.find_library("GL")
    if library_name is None:
        return False
    try:
        ctypes.CDLL(library_name)
    except OSError:
        return False
    return True


HAS_PYSIDE6: Final = _probe_pyside6()
HAS_OPENGL: Final = _probe_libgl()
UI_READY: Final = HAS_PYSIDE6 and HAS_OPENGL

PYTEST_SKIP_MARK: Final | None = (
    pytest.mark.skip(reason=_SKIP_REASON) if not UI_READY else None
)

if UI_READY and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def require_ui() -> None:
    """Skip the current test module when the UI stack is unavailable."""

    if not UI_READY:
        pytest.skip(_SKIP_REASON, allow_module_level=True)
