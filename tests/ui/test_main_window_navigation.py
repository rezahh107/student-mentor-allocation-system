from __future__ import annotations
import pytest

from tests.ui import _headless

_headless.require_ui()

pytestmark = [pytest.mark.ui]
if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark.append(_headless.PYTEST_SKIP_MARK)

import logging
from typing import Tuple


from sma.api.client import APIClient
from sma.ui.presenters.main_presenter import MainPresenter
from sma.ui.windows.main_window import MainWindow


def _build_window(qtbot, offscreen_qapp) -> Tuple[MainWindow, MainPresenter]:
    _ = offscreen_qapp
    client = APIClient(use_mock=True)
    presenter = MainPresenter(client)
    window = MainWindow(presenter)
    qtbot.addWidget(window)
    return window, presenter


def test_show_students_updates_and_logs_on_guard(qtbot, caplog, offscreen_qapp) -> None:
    window, presenter = _build_window(qtbot, offscreen_qapp)

    window.show_students()
    assert presenter.state.current_page == "students"

    caplog.clear()
    window._central_stack = None
    presenter.state.current_page = "dashboard"
    with caplog.at_level(logging.ERROR):
        window.show_students()

    assert presenter.state.current_page == "dashboard"
    assert any("دانش‌آموزان" in message for message in caplog.messages)


def test_show_mentors_updates_and_logs_on_guard(qtbot, caplog, offscreen_qapp) -> None:
    window, presenter = _build_window(qtbot, offscreen_qapp)

    window.show_mentors()
    assert presenter.state.current_page == "mentors"

    caplog.clear()
    window._central_stack = None
    presenter.state.current_page = "dashboard"
    with caplog.at_level(logging.ERROR):
        window.show_mentors()

    assert presenter.state.current_page == "dashboard"
    assert any("منتورها" in message for message in caplog.messages)
