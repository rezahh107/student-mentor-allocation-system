"""Regression tests for UI safety helpers and minimal mode."""
from __future__ import annotations

import logging
import pytest

from src.ui._safety import is_minimal_mode, log_minimal_mode, swallow_ui_error, ui_safe


def test_swallow_ui_error_logs_and_calls_fallback(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="src.ui._safety")
    fallback_called = False

    def fallback() -> None:
        nonlocal fallback_called
        fallback_called = True

    with swallow_ui_error("اجرای قطعه آزمایشی", fallback=fallback):
        raise RuntimeError("boom")

    assert fallback_called is True
    assert any("اجرای قطعه آزمایشی" in record.getMessage() for record in caplog.records)


def test_ui_safe_decorator_invokes_fallback(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="src.ui._safety")
    called: list[str] = []

    @ui_safe("اجرای تابع محافظت‌شده", fallback=lambda: called.append("fallback"))
    def risky() -> None:
        raise ValueError("bad")

    risky()

    assert called == ["fallback"]
    assert any("اجرای تابع محافظت‌شده" in record.getMessage() for record in caplog.records)


def test_minimal_mode_flag(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="src.ui._safety")
    monkeypatch.setenv("UI_MINIMAL", "1")
    assert is_minimal_mode() is True
    log_minimal_mode("صفحه آزمایشی")
    assert any("صفحه آزمایشی" in record.getMessage() for record in caplog.records)

