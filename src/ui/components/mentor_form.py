"""Rich mentor form dialog used for add/edit flows."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QLineEdit,
)

LOGGER = logging.getLogger(__name__)


class MentorFormDialog(QDialog):
    """Dialog for creating or editing mentor records."""

    mentorSaved = Signal(dict)

    def __init__(self, mentor: Optional[Dict[str, Any]] = None, parent=None) -> None:
        super().__init__(parent)
        self.mentor = mentor
        self.is_edit_mode = mentor is not None
        self._build_ui()
        self._wire_validation()
        if self.is_edit_mode:
            self._load_mentor()
        self.setModal(True)
        self.setMinimumSize(420, 520)
        self.setWindowTitle("ویرایش پشتیبان" if self.is_edit_mode else "افزودن پشتیبان")

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QLabel("ویرایش اطلاعات پشتیبان" if self.is_edit_mode else "افزودن پشتیبان جدید")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(header)

        base_group = QGroupBox("اطلاعات پایه")
        base_form = QFormLayout(base_group)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("نام و نام خانوادگی پشتیبان")
        base_form.addRow("نام پشتیبان:", self.name_input)

        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["زن", "مرد"])
        base_form.addRow("جنسیت:", self.gender_combo)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["عادی", "مدرسه‌ای"])
        base_form.addRow("نوع:", self.type_combo)

        self.capacity_spin = QSpinBox()
        self.capacity_spin.setRange(1, 50)
        self.capacity_spin.setValue(10)
        self.capacity_spin.setSuffix(" دانش‌آموز")
        base_form.addRow("ظرفیت:", self.capacity_spin)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("09123456789")
        base_form.addRow("تلفن:", self.phone_input)

        self.active_checkbox = QCheckBox("پشتیبان فعال است")
        self.active_checkbox.setChecked(True)
        base_form.addRow("وضعیت:", self.active_checkbox)

        layout.addWidget(base_group)

        groups_group = QGroupBox("گروه‌های مجاز")
        groups_layout = QVBoxLayout(groups_group)
        self.groups_list = QListWidget()
        self.groups_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for label in ["کنکوری", "متوسطه دوم", "متوسطه اول", "دبستان", "هنرستان", "زبان انگلیسی"]:
            self.groups_list.addItem(label)
        groups_layout.addWidget(QLabel("گروه‌های قابل پشتیبانی:"))
        groups_layout.addWidget(self.groups_list)
        layout.addWidget(groups_group)

        notes_group = QGroupBox("یادداشت")
        notes_layout = QVBoxLayout(notes_group)
        self.notes_text = QTextEdit()
        self.notes_text.setMaximumHeight(80)
        self.notes_text.setPlaceholderText("یادداشت اختیاری...")
        notes_layout.addWidget(self.notes_text)
        layout.addWidget(notes_group)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("ذخیره")
        self.save_btn.setStyleSheet(
            """
            QPushButton {background-color: #4CAF50; color: white; padding: 8px 16px; border-radius: 4px; font-weight: bold;}
            QPushButton:hover {background-color: #45a049;}
            """
        )
        self.cancel_btn = QPushButton("انصراف")
        self.cancel_btn.setStyleSheet(
            """
            QPushButton {background-color: #f44336; color: white; padding: 8px 16px; border-radius: 4px;}
            QPushButton:hover {background-color: #da190b;}
            """
        )
        buttons.addStretch()
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)

        self.save_btn.clicked.connect(self._handle_save)
        self.cancel_btn.clicked.connect(self.reject)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    def _wire_validation(self) -> None:
        self.name_input.textChanged.connect(self._validate_form)
        self.phone_input.textChanged.connect(self._normalise_phone)
        self.capacity_spin.valueChanged.connect(self._validate_form)

    def _normalise_phone(self, text: str) -> None:
        digits = "".join(filter(str.isdigit, text))
        if len(digits) > 11:
            digits = digits[:11]
        if digits != text:
            cursor = self.phone_input.cursorPosition()
            self.phone_input.setText(digits)
            self.phone_input.setCursorPosition(min(cursor, len(digits)))

    def _validate_form(self) -> bool:
        errors = []
        name = self.name_input.text().strip()
        if len(name) < 2:
            errors.append("نام پشتیبان باید حداقل ۲ کاراکتر باشد")
        phone = self.phone_input.text().strip()
        if phone and (len(phone) != 11 or not phone.startswith("09")):
            errors.append("شماره تلفن نامعتبر است")
        if self.capacity_spin.value() <= 0:
            errors.append("ظرفیت باید مقدار مثبت باشد")

        if errors:
            self.save_btn.setToolTip("\n".join(errors))
            self.save_btn.setEnabled(False)
        else:
            self.save_btn.setToolTip("")
            self.save_btn.setEnabled(True)
        return not errors

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _load_mentor(self) -> None:
        if self.mentor is None:
            LOGGER.error(
                "اطلاعات پشتیبان برای بارگذاری فرم در حالت ویرایش موجود نیست."
            )
            return
        self.name_input.setText(self.mentor.get("name", ""))
        self.gender_combo.setCurrentIndex(self.mentor.get("gender", 0))
        self.type_combo.setCurrentIndex(1 if self.mentor.get("is_school") else 0)
        self.capacity_spin.setValue(self.mentor.get("capacity", 10))
        self.phone_input.setText(self.mentor.get("phone", ""))
        self.active_checkbox.setChecked(self.mentor.get("is_active", True))
        self.notes_text.setPlainText(self.mentor.get("notes", ""))
        groups = set(self.mentor.get("groups", []))
        for i in range(self.groups_list.count()):
            item = self.groups_list.item(i)
            item.setSelected(item.text() in groups)

    def _collect_data(self) -> Dict[str, Any]:
        groups = [item.text() for item in self.groups_list.selectedItems()]
        return {
            "name": self.name_input.text().strip(),
            "gender": self.gender_combo.currentIndex(),
            "is_school": self.type_combo.currentIndex() == 1,
            "capacity": self.capacity_spin.value(),
            "phone": self.phone_input.text().strip(),
            "is_active": self.active_checkbox.isChecked(),
            "groups": groups,
            "notes": self.notes_text.toPlainText().strip(),
            "current_load": self.mentor.get("current_load", 0) if self.mentor else 0,
        }

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _handle_save(self) -> None:
        if not self._validate_form():
            QMessageBox.warning(self, "خطای اعتبارسنجی", "لطفاً خطاهای فرم را برطرف کنید")
            return
        mentor_data = self._collect_data()
        reply = QMessageBox.question(
            self,
            "تأیید ذخیره",
            f"آیا از ذخیره اطلاعات پشتیبان '{mentor_data['name']}' اطمینان دارید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.mentorSaved.emit(mentor_data)
            self.accept()
