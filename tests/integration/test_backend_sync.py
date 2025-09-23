from __future__ import annotations

import pytest

from src.api.client import APIClient
from src.api.mock_data import mock_backend
from src.ui.core.event_bus import EventBus
from src.ui.pages.students_page import StudentsPresenter, StudentsTableModel


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
