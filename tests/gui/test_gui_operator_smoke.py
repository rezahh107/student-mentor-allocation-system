from __future__ import annotations

import os
import sys

import pytest


@pytest.mark.skipif(
    os.environ.get("DISPLAY") is None and sys.platform != "win32",
    reason="محیط فاقد نمایشگر است؛ تست GUI رد شد",
)
def test_operator_gui_smoke() -> None:
    from src.tools import gui_operator

    app = gui_operator.OperatorGUI()
    try:
        assert app.root.winfo_exists()
    finally:
        app.root.destroy()
