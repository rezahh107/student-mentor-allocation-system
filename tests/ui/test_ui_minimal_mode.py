"""UI minimal mode regressions."""
from __future__ import annotations

import logging
import pytest

from tests.ui import _headless

_headless.require_ui()

pytestmark = [pytest.mark.ui]
if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark.append(_headless.PYTEST_SKIP_MARK)


def test_allocation_page_minimal_mode(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    offscreen_qapp,
) -> None:
    caplog.set_level(logging.INFO, logger="sma.ui.pages.allocation_page")
    monkeypatch.setenv("UI_MINIMAL", "1")
    from sma.ui.pages.allocation_page import AllocationPage

    page = AllocationPage()
    assert getattr(page, "_minimal_mode", False) is True
    assert any("صفحه تخصیص" in record.getMessage() for record in caplog.records)
    assert page.load_statistics() is None
