"""Qt table model for mentor listings."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class MentorsTableModel(QAbstractTableModel):
    """Display mentors with RTL-friendly headers and status colouring."""

    def __init__(self) -> None:
        super().__init__()
        self.headers = [
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
        self.mentors: List[Dict[str, Any]] = []
        self._colors = {
            "active": QColor(144, 238, 144),
            "inactive": QColor(255, 182, 193),
            "full": QColor(255, 204, 128),
            "empty": QColor(224, 224, 224),
        }

    # ------------------------------------------------------------------
    # Qt model overrides
    # ------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.mentors)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return len(self.headers)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        mentor = self.mentors[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            return self._display_value(mentor, column)
        if role == Qt.BackgroundRole:
            return self._background_color(mentor)
        if role == Qt.TextAlignmentRole:
            if column in {0, 4, 5, 6, 7}:
                return Qt.AlignCenter
            return Qt.AlignRight | Qt.AlignVCenter
        return None

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------
    def load_mentors(self, mentors: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self.mentors = mentors.copy()
        self.endResetModel()

    def add_mentor(self, mentor: Dict[str, Any]) -> None:
        row = len(self.mentors)
        self.beginInsertRows(QModelIndex(), row, row)
        self.mentors.append(mentor)
        self.endInsertRows()

    def update_mentor(self, mentor_id: int, mentor: Dict[str, Any]) -> None:
        for row, existing in enumerate(self.mentors):
            if existing["id"] == mentor_id:
                self.mentors[row] = mentor
                top_left = self.index(row, 0)
                bottom_right = self.index(row, self.columnCount() - 1)
                self.dataChanged.emit(top_left, bottom_right)
                break

    def remove_mentor(self, mentor_id: int) -> None:
        for row, mentor in enumerate(self.mentors):
            if mentor["id"] == mentor_id:
                self.beginRemoveRows(QModelIndex(), row, row)
                del self.mentors[row]
                self.endRemoveRows()
                break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def get_mentor_by_row(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self.mentors):
            return self.mentors[row].copy()
        return None

    def get_selected(self, selection_model) -> List[Dict[str, Any]]:
        mentors: List[Dict[str, Any]] = []
        for idx in selection_model.selectedRows():
            mentor = self.get_mentor_by_row(idx.row())
            if mentor:
                mentors.append(mentor)
        return mentors

    def _display_value(self, mentor: Dict[str, Any], column: int) -> str:
        if column == 0:
            return str(mentor.get("id", ""))
        if column == 1:
            return mentor.get("name", "")
        if column == 2:
            return "زن" if mentor.get("gender") == 0 else "مرد"
        if column == 3:
            return "مدرسه‌ای" if mentor.get("is_school") else "عادی"
        if column == 4:
            return str(mentor.get("capacity", 0))
        if column == 5:
            return str(mentor.get("current_load", 0))
        if column == 6:
            return str(mentor.get("remaining_capacity", mentor.get("capacity", 0)))
        if column == 7:
            capacity = mentor.get("capacity", 0)
            load = mentor.get("current_load", 0)
            return f"{(load / capacity * 100):.1f}%" if capacity else "0%"
        if column == 8:
            if not mentor.get("is_active", True):
                return "غیرفعال"
            if mentor.get("remaining_capacity", 0) == 0:
                return "پر"
            if mentor.get("current_load", 0) == 0:
                return "خالی"
            return "فعال"
        if column == 9:
            return mentor.get("phone", "")
        return ""

    def _background_color(self, mentor: Dict[str, Any]) -> QColor:
        if not mentor.get("is_active", True):
            return self._colors["inactive"]
        if mentor.get("remaining_capacity", 0) == 0:
            return self._colors["full"]
        if mentor.get("current_load", 0) == 0:
            return self._colors["empty"]
        return self._colors["active"]
