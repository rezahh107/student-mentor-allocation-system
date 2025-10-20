"""تست تضمین عدم بلاک شدن تکرار اجرای دیسپچر."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from sma.tools.gui_operator import OperatorGUI


def _dummy_dispatcher_factory(_publisher):
    dispatcher = SimpleNamespace(dispatch_once=lambda: 0)

    def cleanup() -> None:
        return None

    return dispatcher, cleanup


def test_duplicate_start_is_non_blocking() -> None:
    try:
        gui = OperatorGUI(dispatcher_factory=_dummy_dispatcher_factory)
    except RuntimeError as exc:  # pragma: no cover - در محیط بدون نمایشگر
        if "GUI_HEADLESS_SKIPPED" in str(exc):
            pytest.skip(str(exc))
        raise

    start = time.perf_counter()
    gui._start_dispatcher()
    first_duration = time.perf_counter() - start
    assert first_duration < 0.5

    second_start = time.perf_counter()
    gui._start_dispatcher()
    second_duration = time.perf_counter() - second_start
    assert second_duration < 0.1

    gui._drain_queue_for_test()
    assert "هشدار: فرایند در حال اجراست" == gui.banner_var.get()

    gui._stop_dispatcher()
    gui._drain_queue_for_test()
    gui.root.destroy()
