from __future__ import annotations

import logging
import os
import warnings

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

import pytest

pytest_plugins = ["pytest_asyncio.plugin", "tests._compat.pytest_asyncio_scope"]


def pytest_configure(config: pytest.Config) -> None:
    """رفتار اخطارهای فرسودگی را در محیط محلی ملایم می‌کند."""

    warnings.filterwarnings(
        "ignore",
        message="The 'app' shortcut is now deprecated",
        category=DeprecationWarning,
        module="httpx._client",
    )
    if os.getenv("PYTEST_CI") == "1":
        return

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx may be absent locally
        return

    if not getattr(httpx.Client.__init__, "_phase6_patched", False):
        original_init = httpx.Client.__init__

        def _wrapped_init(self, *args, **kwargs):
            if kwargs.get("app") is not None:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    return original_init(self, *args, **kwargs)
            return original_init(self, *args, **kwargs)

        _wrapped_init._phase6_patched = True  # type: ignore[attr-defined]
        httpx.Client.__init__ = _wrapped_init  # type: ignore[assignment]

    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").propagate = False


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
