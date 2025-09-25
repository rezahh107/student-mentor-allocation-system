from __future__ import annotations

import pytest

pytest.importorskip(
    "PyQt5",
    reason="GUI_HEADLESS_SKIPPED: محیط آزمایشی فاقد PyQt5 و وابستگی‌های گرافیکی است.",
)

from src.api.client import APIClient
from src.api.mock_data import mock_backend
from src.ui.core.event_bus import EventBus

try:
    from src.ui.pages.students_page import StudentsPresenter, StudentsTableModel
except ImportError as exc:  # pragma: no cover - headless environments
    pytest.skip(
        f"GUI_HEADLESS_SKIPPED: محیط گرافیکی در دسترس نیست ({exc})",
        allow_module_level=True,
    )


@pytest.mark.asyncio
async def test_ui_refresh_reflects_backend_changes(qtbot):
    """Presenter refresh should propagate new backend data into the table model."""

    mock_backend.reset()
    client = APIClient(use_mock=True)
    presenter = StudentsPresenter(client, EventBus())
    model = StudentsTableModel()

    initial_students, initial_total = await presenter.load_students()
    await model.load_data(initial_students)
    initial_count = model.rowCount()
    assert 0 < initial_count <= initial_total

    await mock_backend.create_student(
        {
            "first_name": "سینا",
            "last_name": "کاظمی",
            "gender": 1,
            "center": 1,
            "education_status": 1,
            "grade_level": "konkoori",
        }
    )

    updated_students, updated_total = await presenter.load_students()
    await model.load_data(updated_students)

    assert updated_total > initial_total
    assert model.rowCount() > 0
