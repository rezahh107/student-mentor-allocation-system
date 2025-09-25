"""کمک‌کننده برای وارد کردن PySide6 با پیام فارسی در صورت نبودن وابستگی."""
from __future__ import annotations

import importlib
from typing import Any

QtCore: Any | None
QtGui: Any | None
QtWidgets: Any | None
_QT_IMPORT_ERROR: Exception | None = None

try:  # pragma: no cover - در محیط headless ممکن است شکست بخورد
    QtCore = importlib.import_module("PySide6.QtCore")
    QtGui = importlib.import_module("PySide6.QtGui")
    QtWidgets = importlib.import_module("PySide6.QtWidgets")
except Exception as exc:  # pragma: no cover - وابستگی اختیاری
    QtCore = None
    QtGui = None
    QtWidgets = None
    _QT_IMPORT_ERROR = exc
else:
    _QT_IMPORT_ERROR = None

HEADLESS_IMPORT_MESSAGE = (
    "GUI_HEADLESS_SKIPPED: کتابخانه PySide6 برای اجرای رابط کاربری نصب یا پیکربندی نشده است."
)


def require_qt() -> None:
    """تضمین در دسترس بودن PySide6 یا تولید پیام فارسی."""

    if QtWidgets is None:
        raise RuntimeError(
            f"{HEADLESS_IMPORT_MESSAGE} ({_QT_IMPORT_ERROR})"
        )
