from __future__ import annotations

from PyQt5.QtCore import Qt

from src.ui.windows.main_window import MainWindow
from src.ui.presenters.main_presenter import MainPresenter
from src.api.client import APIClient


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

