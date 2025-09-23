from __future__ import annotations

import pytest
from src.ui.pages.allocation_page import AllocationPage
from src.ui.pages.allocation_presenter import AllocationPresenter
from src.ui.services.allocation_backend import MockBackendService
from PySide6.QtWidgets import QMessageBox


@pytest.fixture(autouse=True)
def suppress_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)


@pytest.fixture
def integrated_system(qtbot):
    backend = MockBackendService(student_count=30, mentor_count=8)
    presenter = AllocationPresenter(backend)
    page = AllocationPage()
    qtbot.addWidget(page)
    page.set_presenter(presenter)
    return {"backend": backend, "presenter": presenter, "page": page}


class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_allocation_flow(self, integrated_system):
        page: AllocationPage = integrated_system["page"]

        await page.presenter.load_statistics()
        page.same_center_only.setChecked(True)
        page.prefer_lower_load.setChecked(True)

        await page.start_allocation()

        assert page.last_results is not None
        assert page.last_results["successful"] >= 0
        assert page.view_results_button.isEnabled()

    @pytest.mark.asyncio
    async def test_excel_export_integration(self, integrated_system, tmp_path):
        presenter: AllocationPresenter = integrated_system["presenter"]

        results = {
            "successful": 10,
            "failed": 2,
            "assignments": [
                {"student_id": 1, "mentor_id": 1, "priority_score": 150},
                {"student_id": 2, "mentor_id": 2, "priority_score": 140},
            ],
            "errors": [],
        }

        file_path = tmp_path / "test_results.xlsx"
        success = await presenter.export_results(results, str(file_path))

        assert success
        assert file_path.exists()
