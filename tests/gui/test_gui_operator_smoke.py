from types import SimpleNamespace

import pytest

from sma.tools.gui_operator import OperatorGUI


def _dummy_dispatcher_factory(_publisher):
    dispatcher = SimpleNamespace(dispatch_once=lambda: 0)

    def cleanup() -> None:
        return None

    return dispatcher, cleanup


def test_gui_operator_instantiates_and_processes_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        gui = OperatorGUI(dispatcher_factory=_dummy_dispatcher_factory)
    except RuntimeError as exc:  # pragma: no cover - در محیط بدون نمایشگر
        if "GUI_HEADLESS_SKIPPED" in str(exc):
            pytest.skip(str(exc))
        raise

    gui.enqueue_log("نمونه پیام")
    gui.enqueue_status("evt-1", "PENDING", {"delay": 0.5})
    gui._drain_queue_for_test()
    assert "PENDING" in gui.status_var.get()
    gui.root.destroy()
