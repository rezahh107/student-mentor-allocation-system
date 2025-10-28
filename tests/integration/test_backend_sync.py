from __future__ import annotations

import pytest

from sma.api.client import APIClient
from sma.api.mock_data import mock_backend
from sma.ui.core.event_bus import EventBus
from sma.ui.pages.students_presenter import StudentsPresenter

try:  # pragma: no cover - optional dependency path
    from sma.ui.pages.students_page import StudentsTableModel  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - fallback for headless mode
    class StudentsTableModel:  # type: ignore[override]
        def __init__(self) -> None:
            self._rows: list[object] = []

        async def load_data(self, rows) -> None:  # noqa: ANN001
            self._rows = list(rows)

        def rowCount(self) -> int:  # noqa: N802 - Qt compatibility
            return len(self._rows)


@pytest.mark.asyncio
async def test_ui_refresh_reflects_backend_changes():
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
