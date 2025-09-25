from __future__ import annotations
import pytest

from tests.ui import _headless

_headless.require_ui()

pytestmark = [pytest.mark.ui]
if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark.append(_headless.PYTEST_SKIP_MARK)

import asyncio

from PyQt5.QtWidgets import QFileDialog

from src.api.client import APIClient
from src.ui.core.event_bus import EventBus
from src.ui.pages.students_page import StudentsPage
from src.ui.pages.dialogs import student_dialog as student_dialog_module


@pytest.mark.asyncio
async def test_students_page_load_filter_add_bulk_export(qtbot, tmp_path, monkeypatch):
    client = APIClient(use_mock=True)
    page = StudentsPage(client, EventBus())
    qtbot.addWidget(page)
    page.show()

    # Wait for initial load
    async def wait_loaded():
        for _ in range(50):
            if page.model.rowCount() > 0:
                return True
            await asyncio.sleep(0.05)
        return False

    assert await wait_loaded()
    initial_rows = page.model.rowCount()

    # Apply gender filter to female (index 1)
    page.filter_panel.gender_combo.setCurrentIndex(1)
    await page.on_filters_changed()
    # Ensure rows filtered (may be < initial)
    assert page.model.rowCount() <= initial_rows
    # All rows should show Persian gender text for female
    for r in range(page.model.rowCount()):
        val = page.model.data(page.model.index(r, 7))
        assert val == "زن"

    # Add student: patch dialog to auto-accept and return data
    monkeypatch.setattr(student_dialog_module.StudentDialog, "exec_", lambda self: self.Accepted)
    monkeypatch.setattr(
        student_dialog_module.StudentDialog,
        "get_student_data",
        lambda self: {
            "first_name": "حسین",
            "last_name": "محمدی",
            "national_code": "0012345678",
            "phone": "+989121234567",
            "birth_date": "2005-01-01",
            "gender": 1,
            "center": 1,
            "education_status": 1,
            "grade_level": "konkoori",
            "school_type": "normal",
            "school_code": None,
        },
    )
    await page.on_add_clicked()
    await page.on_refresh_clicked()
    assert page.model.rowCount() >= initial_rows

    # Enable selection mode and select all
    page.on_toggle_selection_mode(True)
    page.on_select_all(True)
    assert len(page.model.selected_ids) == page.model.rowCount()

    # Bulk export selected
    out_path = tmp_path / "selected.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out_path), "Excel Files (*.xlsx)"))
    await page.export_selected()
    assert out_path.exists()
