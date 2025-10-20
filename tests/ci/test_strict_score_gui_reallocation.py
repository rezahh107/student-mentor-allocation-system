from __future__ import annotations

import pytest

from sma.phase9_readiness.report import apply_gui_reallocation


def test_gui_out_of_scope_reallocation_applies() -> None:
    axes = {"performance": 40.0, "excel": 40.0, "gui": 15.0}
    adjusted, message = apply_gui_reallocation(axes, gui_in_scope=False)
    assert adjusted["performance"] == pytest.approx(49.0)
    assert adjusted["excel"] == pytest.approx(46.0)
    assert adjusted["gui"] == 0.0
    assert "خارج از محدوده" in message


def test_gui_in_scope_no_change() -> None:
    axes = {"performance": 38.0, "excel": 37.0, "gui": 12.0}
    adjusted, message = apply_gui_reallocation(axes, gui_in_scope=True)
    assert adjusted == axes
    assert "تغییری نکرد" in message
