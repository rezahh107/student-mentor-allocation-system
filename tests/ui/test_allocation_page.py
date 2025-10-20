from __future__ import annotations
import pytest

from tests.ui import _headless

_headless.require_ui()

pytestmark = [pytest.mark.ui]
if _headless.PYTEST_SKIP_MARK is not None:
    pytestmark.append(_headless.PYTEST_SKIP_MARK)

import asyncio
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from sma.core.models import Mentor, Student
from sma.ui.pages.allocation_page import AllocationPage
from sma.ui.services.allocation_backend import IBackendService


class DummyBackend(IBackendService):
    def __init__(self) -> None:
        self._students = [
            Student(id=1, gender=1, grade_level=10, center_id=1, name="علی احمدی"),
            Student(id=2, gender=0, grade_level=11, center_id=1, name="سارا محمدی"),
        ]
        self._mentors = [
            Mentor(
                id=1,
                gender=1,
                supported_grades=[10, 11],
                max_capacity=10,
                current_students=5,
                center_id=1,
                name="استاد احمدی",
            ),
            Mentor(
                id=2,
                gender=0,
                supported_grades=[11],
                max_capacity=8,
                current_students=3,
                center_id=1,
                name="خانم رضایی",
            ),
        ]
        self.saved_results: List[Dict] = []
        self.statistics_calls = 0

    async def get_unassigned_students(self, filters: Optional[Dict] = None) -> List[Student]:
        return list(self._students)

    async def get_available_mentors(self, filters: Optional[Dict] = None) -> List[Mentor]:
        return list(self._mentors)

    async def save_allocation_results(self, results: Dict) -> bool:
        self.saved_results.append(results)
        return True

    async def get_allocation_statistics(self) -> Dict:
        self.statistics_calls += 1
        total_capacity = sum(m.max_capacity for m in self._mentors)
        used_capacity = sum(m.current_students for m in self._mentors)
        return {
            "total_students": len(self._students),
            "total_mentors": len(self._mentors),
            "total_capacity": total_capacity,
            "available_capacity": total_capacity - used_capacity,
        }


@pytest.fixture
def dummy_backend() -> DummyBackend:
    return DummyBackend()


@pytest.fixture(autouse=True)
def suppress_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)


class TestAllocationPage:
    def test_page_initialization(self, qtbot, dummy_backend: DummyBackend):
        page = AllocationPage(dummy_backend)
        qtbot.addWidget(page)

        assert page.windowTitle() == ""
        assert page.start_button.isEnabled()
        assert not page.view_results_button.isEnabled()
        assert page.results_summary.text() == "هنوز تخصیصی انجام نشده"

    def test_settings_checkboxes(self, qtbot, dummy_backend: DummyBackend):
        page = AllocationPage(dummy_backend)
        qtbot.addWidget(page)

        assert page.same_center_only.isChecked()
        assert page.prefer_lower_load.isChecked()

        qtbot.mouseClick(page.same_center_only, Qt.LeftButton)
        assert not page.same_center_only.isChecked()

    @pytest.mark.asyncio
    async def test_successful_allocation(self, qtbot, dummy_backend: DummyBackend):
        page = AllocationPage(dummy_backend)
        qtbot.addWidget(page)

        await page.start_allocation()

        assert page.last_results is not None
        assert page.last_results["successful"] >= 0
        assert page.view_results_button.isEnabled()
        assert len(dummy_backend.saved_results) == 1

    def test_statistics_display(self, qtbot, dummy_backend: DummyBackend):
        page = AllocationPage(dummy_backend)
        qtbot.addWidget(page)

        page.update_statistics_display(
            {"students": 150, "mentors": 25, "total_capacity": 200, "available_capacity": 50}
        )

        assert page.students_count_label.text() == "150"
        assert page.mentors_count_label.text() == "25"
        assert page.total_capacity_label.text() == "200"
        assert page.available_capacity_label.text() == "50"
