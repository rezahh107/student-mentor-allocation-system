"""Pytest configuration for UI test suite."""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.ui import _headless

if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark = _headless.PYTEST_SKIP_MARK


@pytest.fixture(scope="session")
def offscreen_qapp() -> Iterator["QApplication"]:
    """Provide a QApplication instance that works in offscreen mode."""

    _headless.require_ui()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    created = app is None
    if created:
        app = QApplication([])
    assert app is not None
    yield app
    if created:
        app.quit()
