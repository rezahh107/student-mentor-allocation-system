"""Mentor management UI page."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from src.ui.qt_optional import QtCore, QtGui, QtWidgets, require_qt

require_qt()

Qt = QtCore.Qt
QFont = QtGui.QFont
QComboBox = QtWidgets.QComboBox
QDialog = QtWidgets.QDialog
QGroupBox = QtWidgets.QGroupBox
QHBoxLayout = QtWidgets.QHBoxLayout
QLabel = QtWidgets.QLabel
QMessageBox = QtWidgets.QMessageBox
QPushButton = QtWidgets.QPushButton
QTableView = QtWidgets.QTableView
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget
QApplication = QtWidgets.QApplication

from src.ui.components.mentor_form import MentorFormDialog
from src.ui.models.mentors_model import MentorsTableModel
from src.ui.services.mock_mentor_service import MockMentorService

logger = logging.getLogger(__name__)


class MentorStatsWidget(QWidget):
    """Compact widget showing aggregate mentor statistics."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.total_label = self._build_label("کل: 0")
        self.active_label = self._build_label("فعال: 0")
        self.capacity_label = self._build_label("ظرفیت کل: 0")
        self.load_label = self._build_label("بار فعلی: 0")
        self.available_label = self._build_label("ظرفیت آزاد: 0")
        for lbl in [
            self.total_label,
            self.active_label,
            self.capacity_label,
            self.load_label,
            self.available_label,
        ]:
            layout.addWidget(lbl)
        layout.addStretch()

    @staticmethod
    def _build_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            """
            QLabel {
                background-color: #e3f2fd;
                border: 1px solid #2196f3;
                border-radius: 4px;
                padding: 6px 10px;
                font-weight: bold;
                color: #0d47a1;
            }
            """
        )
        return label

    def update_stats(self, stats: Dict[str, Any]) -> None:
        self.total_label.setText(f"کل: {stats['total']}")
        self.active_label.setText(f"فعال: {stats['active']}")
        self.capacity_label.setText(f"ظرفیت کل: {stats['total_capacity']}")
        self.load_label.setText(f"بار فعلی: {stats['total_load']}")
        available = stats['total_capacity'] - stats['total_load']
        self.available_label.setText(f"ظرفیت آزاد: {available}")


class MentorsPage(QWidget):
    """Main page for managing mentors inside the SmartAlloc UI."""

    def __init__(self, backend_service: Optional[Any] = None) -> None:
        super().__init__()
        self.backend = backend_service or MockMentorService()
        self._current_filters: Dict[str, Any] = {}
        self._build_ui()
        self.load_mentors()

    # ------------------------------------------------------------------
    # UI assembly
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("مدیریت پشتیبان‌های آموزشی")
        title.setStyleSheet(
            """
            QLabel {
                font-size: 20px;
                font-weight: bold;
                color: #1976d2;
                margin: 6px 0;
                padding: 10px;
                background-color: #e3f2fd;
                border-radius: 8px;
            }
            """
        )
        layout.addWidget(title)

        self.stats_widget = MentorStatsWidget()
        layout.addWidget(self.stats_widget)

        toolbar = QHBoxLayout()
        button_style = (
            """
            QPushButton {background-color: #2196f3; color: white; border: none; padding: 8px 14px; border-radius: 6px; font-weight: bold;}
            QPushButton:hover {background-color: #1976d2;}
            QPushButton:pressed {background-color: #0d47a1;}
            QPushButton:disabled {background-color: #cccccc; color: #666666;}
            """
        )
        self.add_btn = QPushButton("➕ افزودن پشتیبان")
        self.edit_btn = QPushButton("✏️ ویرایش")
        self.delete_btn = QPushButton("🗑️ حذف")
        self.refresh_btn = QPushButton("🔄 بروزرسانی")
        for btn in (self.add_btn, self.edit_btn, self.refresh_btn):
            btn.setStyleSheet(button_style)
        self.delete_btn.setStyleSheet(
            button_style.replace("#2196f3", "#f44336").replace("#1976d2", "#d32f2f").replace("#0d47a1", "#b71c1c")
        )
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        filters_group = QGroupBox("فیلترها")
        filters_layout = QHBoxLayout(filters_group)
        filters_layout.addWidget(QLabel("جنسیت:"))
        self.gender_filter = QComboBox()
        self.gender_filter.addItems(["همه", "زن", "مرد"])
        filters_layout.addWidget(self.gender_filter)
        filters_layout.addWidget(QLabel("نوع:"))
        self.type_filter = QComboBox()
        self.type_filter.addItems(["همه", "عادی", "مدرسه‌ای"])
        filters_layout.addWidget(self.type_filter)
        filters_layout.addWidget(QLabel("وضعیت:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["همه", "فعال", "غیرفعال"])
        filters_layout.addWidget(self.status_filter)
        filters_layout.addStretch()
        layout.addWidget(filters_group)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet(
            """
            QTableView {gridline-color: #e0e0e0; background-color: white; alternate-background-color: #f5f5f5; selection-background-color: #2196f3;}
            QHeaderView::section {background-color: #1976d2; color: white; padding: 8px; font-weight: bold; border: none;}
            """
        )
        self.table.setFont(QFont("Tahoma", 10))
        self.model = MentorsTableModel()
        self.table.setModel(self.model)
        layout.addWidget(self.table)

        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

        # Signal connections
        self.add_btn.clicked.connect(self.add_mentor)
        self.edit_btn.clicked.connect(self.edit_mentor)
        self.delete_btn.clicked.connect(self.delete_mentor)
        self.refresh_btn.clicked.connect(self.load_mentors)
        self.gender_filter.currentIndexChanged.connect(self.apply_filters)
        self.type_filter.currentIndexChanged.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)

    # ------------------------------------------------------------------
    # Data interactions
    # ------------------------------------------------------------------
    def load_mentors(self) -> None:
        try:
            mentors = self.backend.get_all_mentors(self._current_filters)
            self.model.load_mentors(mentors)
            self.stats_widget.update_stats(self.backend.get_mentor_stats())
            self.apply_filters()
            logger.info("Mentor list refreshed (%s rows)", len(mentors))
        except Exception as exc:  # pragma: no cover - UI path
            logger.exception("Failed to load mentors")
            QMessageBox.critical(self, "خطا", f"خطا در بارگذاری پشتیبان‌ها:\n{exc}")

    def apply_filters(self) -> None:
        filters: Dict[str, Any] = {}
        if self.gender_filter.currentIndex() == 1:
            filters["gender"] = 0
        elif self.gender_filter.currentIndex() == 2:
            filters["gender"] = 1
        if self.type_filter.currentIndex() == 1:
            filters["is_school"] = False
        elif self.type_filter.currentIndex() == 2:
            filters["is_school"] = True
        if self.status_filter.currentIndex() == 1:
            filters["is_active"] = True
        elif self.status_filter.currentIndex() == 2:
            filters["is_active"] = False
        self._current_filters = filters
        mentors = self.backend.get_all_mentors(filters)
        self.model.load_mentors(mentors)

    def _selection_changed(self) -> None:
        has_selection = bool(self.table.selectionModel().selectedRows())
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # CRUD actions
    # ------------------------------------------------------------------
    def add_mentor(self) -> None:
        dialog = MentorFormDialog(parent=self)
        if dialog.exec() == QDialog.Accepted:
            try:
                data = dialog.get_mentor_data()
                self.backend.create_mentor(data)
                self.load_mentors()
                QMessageBox.information(self, "موفقیت", f"پشتیبان '{data['name']}' با موفقیت اضافه شد.")
            except Exception as exc:  # pragma: no cover - UI path
                logger.exception("Failed to create mentor")
                QMessageBox.critical(self, "خطا", f"خطا در افزودن پشتیبان:\n{exc}")

    def edit_mentor(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            QMessageBox.warning(self, "هشدار", "لطفاً یک پشتیبان انتخاب کنید.")
            return
        mentor = self.model.get_mentor_by_row(selection[0].row())
        if not mentor:
            QMessageBox.warning(self, "خطا", "پشتیبان انتخاب شده یافت نشد.")
            return
        dialog = MentorFormDialog(mentor, parent=self)
        if dialog.exec() == QDialog.Accepted:
            try:
                data = dialog.get_mentor_data()
                updated = self.backend.update_mentor(mentor["id"], data)
                self.model.update_mentor(updated["id"], updated)
                self.stats_widget.update_stats(self.backend.get_mentor_stats())
                QMessageBox.information(self, "موفقیت", "پشتیبان با موفقیت بروزرسانی شد.")
            except Exception as exc:
                logger.exception("Failed to update mentor")
                QMessageBox.critical(self, "خطا", f"خطا در بروزرسانی پشتیبان:\n{exc}")

    def delete_mentor(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            QMessageBox.warning(self, "هشدار", "لطفاً یک پشتیبان انتخاب کنید.")
            return
        mentor = self.model.get_mentor_by_row(selection[0].row())
        if not mentor:
            QMessageBox.warning(self, "خطا", "پشتیبان انتخاب شده یافت نشد.")
            return
        reply = QMessageBox.question(
            self,
            "تأیید حذف",
            f"آیا از حذف پشتیبان '{mentor['name']}' اطمینان دارید؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                self.backend.delete_mentor(mentor["id"])
                self.model.remove_mentor(mentor["id"])
                self.stats_widget.update_stats(self.backend.get_mentor_stats())
                QMessageBox.information(self, "موفقیت", "پشتیبان با موفقیت حذف شد.")
            except Exception as exc:
                logger.exception("Failed to delete mentor")
                QMessageBox.critical(self, "خطا", f"خطا در حذف پشتیبان:\n{exc}")


if __name__ == "__main__":  # pragma: no cover - manual testing helper
    import sys

    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(QFont("Tahoma", 10))
    window = MentorsPage()
    window.resize(900, 600)
    window.show()
    sys.exit(app.exec())
