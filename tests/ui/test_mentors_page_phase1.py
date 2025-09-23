"""Phase 1 tests for MentorsPage UI."""
from __future__ import annotations

from typing import Dict

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from src.ui.components.mentor_form import MentorFormDialog
from src.ui.models.mentors_model import MentorsTableModel
from src.ui.pages.mentors_page import MentorsPage
from src.ui.services.mock_mentor_service import MockMentorService


class TestMentorTableModel:
    def test_empty_model(self) -> None:
        model = MentorsTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 10

    def test_load_mentors(self) -> None:
        model = MentorsTableModel()
        mentors = [
            {
                "id": 1,
                "name": "تست منتور",
                "gender": 0,
                "is_school": False,
                "capacity": 10,
                "current_load": 5,
                "remaining_capacity": 5,
                "is_active": True,
                "phone": "09123456789",
            }
        ]
        model.load_mentors(mentors)
        assert model.rowCount() == 1
        assert model.data(model.index(0, 0), Qt.DisplayRole) == "1"
        assert model.data(model.index(0, 1), Qt.DisplayRole) == "تست منتور"
        assert model.data(model.index(0, 2), Qt.DisplayRole) == "زن"
        assert model.data(model.index(0, 3), Qt.DisplayRole) == "عادی"

    def test_header_data(self) -> None:
        model = MentorsTableModel()
        expected = [
            "شناسه",
            "نام پشتیبان",
            "جنسیت",
            "نوع",
            "ظرفیت کل",
            "بار فعلی",
            "ظرفیت باقی",
            "درصد استفاده",
            "وضعیت",
            "تلفن",
        ]
        for idx, label in enumerate(expected):
            assert model.headerData(idx, Qt.Horizontal, Qt.DisplayRole) == label


class TestMentorFormDialog:
    @pytest.fixture
    def dialog(self, qtbot):
        dlg = MentorFormDialog()
        qtbot.addWidget(dlg)
        return dlg

    def test_defaults(self, dialog: MentorFormDialog) -> None:
        assert dialog.windowTitle() == "افزودن پشتیبان"
        assert dialog.name_input.text() == ""
        assert dialog.gender_combo.currentIndex() == 0
        assert dialog.type_combo.currentIndex() == 0
        assert dialog.capacity_spin.value() == 10
        assert dialog.active_checkbox.isChecked()

    def test_validation_blocks_empty_name(self, dialog: MentorFormDialog) -> None:
        dialog.name_input.setText(" ")
        dialog._handle_save()  # noqa: SLF001
        assert dialog.result() == 0


class TestMentorsPage:
    @pytest.fixture
    def mock_service(self) -> MockMentorService:
        return MockMentorService()

    @pytest.fixture
    def mentors_page(self, qtbot, mock_service: MockMentorService) -> MentorsPage:
        page = MentorsPage(backend_service=mock_service)
        qtbot.addWidget(page)
        return page

    @pytest.fixture(autouse=True)
    def suppress_message_boxes(self, monkeypatch):
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
        monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    def test_initial_load_populates_model(self, mentors_page: MentorsPage, mock_service: MockMentorService) -> None:
        assert mentors_page.model.rowCount() == len(mock_service.get_all_mentors())

    def test_add_mentor_uses_form_data(self, mentors_page: MentorsPage, monkeypatch) -> None:
        sample: Dict[str, any] = {
            "name": "پشتیبان جدید",
            "gender": 1,
            "is_school": False,
            "capacity": 10,
            "phone": "09120000000",
            "is_active": True,
            "groups": [],
            "notes": "",
            "current_load": 0,
        }

        class StubDialog:
            def __init__(self, *_, **__):
                pass

            def exec(self) -> int:
                return QDialog.Accepted

            def get_mentor_data(self):
                return sample

        monkeypatch.setattr("src.ui.pages.mentors_page.MentorFormDialog", StubDialog)
        initial = mentors_page.model.rowCount()
        mentors_page.add_mentor()
        assert mentors_page.model.rowCount() == initial + 1

    def test_delete_mentor_confirms_and_removes(self, mentors_page: MentorsPage, monkeypatch) -> None:
        mentors_page.backend._mentors[0]["current_load"] = 0
        mentors_page.backend._mentors[0]["remaining_capacity"] = mentors_page.backend._mentors[0]["capacity"]
        mentors_page.table.selectRow(0)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
        initial = mentors_page.model.rowCount()
        mentors_page.delete_mentor()
        assert mentors_page.model.rowCount() == initial - 1

    def test_edit_without_selection_shows_warning(self, mentors_page: MentorsPage, monkeypatch) -> None:
        called = {"warned": False}

        def fake_warning(*args, **kwargs):
            called["warned"] = True
            return QMessageBox.Ok

        monkeypatch.setattr(QMessageBox, "warning", fake_warning)
        mentors_page.edit_mentor()
        assert called["warned"]

