from __future__ import annotations

import os
import warnings

import pytest

pytest_plugins = ["tests._compat.pytest_asyncio_scope"]


def pytest_configure(config: pytest.Config) -> None:
    """رفتار اخطارهای فرسودگی را در محیط محلی ملایم می‌کند."""

    if os.getenv("PYTEST_CI") == "1":
        return
    warnings.filterwarnings("default", category=DeprecationWarning)


@pytest.fixture(autouse=True)
def suppress_qt_message_boxes(monkeypatch):
    """Prevent modal QMessageBox dialogs from blocking headless test runs."""

    if os.environ.get("PYTEST_QT_ALLOW_DIALOGS"):
        yield
        return

    def _patch_module(module_path: str) -> None:
        try:
            module = __import__(module_path, fromlist=["QMessageBox"])
            message_box = getattr(module, "QMessageBox")
        except Exception:  # pragma: no cover - module may be absent
            return

        ok_value = getattr(message_box, "Ok", getattr(message_box, "Accepted", 0))
        yes_value = getattr(message_box, "Yes", ok_value)

        def _return(value):  # type: ignore[override]
            return lambda *args, **kwargs: value

        monkeypatch.setattr(message_box, "information", _return(ok_value))
        monkeypatch.setattr(message_box, "warning", _return(ok_value))
        monkeypatch.setattr(message_box, "critical", _return(ok_value))
        monkeypatch.setattr(message_box, "question", _return(yes_value))

    _patch_module("PyQt5.QtWidgets")
    _patch_module("PySide6.QtWidgets")

    yield
