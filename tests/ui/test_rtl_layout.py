from __future__ import annotations
import pytest

from tests.ui import _headless

_headless.require_ui()

pytestmark = [pytest.mark.ui]
if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark.append(_headless.PYTEST_SKIP_MARK)



from PyQt5.QtCore import Qt

from sma.ui.windows.main_window import MainWindow
from sma.ui.presenters.main_presenter import MainPresenter
from sma.api.client import APIClient


def test_app_is_rtl_and_persian_labels(qtbot):
    client = APIClient(use_mock=True)
    presenter = MainPresenter(client)
    w = MainWindow(presenter)
    qtbot.addWidget(w)
    w.show()

    # RTL layout enforced at app level by theme
    assert w.layoutDirection() == Qt.RightToLeft

    # Check a known Persian text appears in menubar or status
    assert "دانش‌آموزان" in [a.text() for a in w.menuBar().actions()[1].menu().actions()]
