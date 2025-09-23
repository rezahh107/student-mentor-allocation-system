from __future__ import annotations

from typing import Optional

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from PyQt5.QtCore import QDate, QLocale
from PyQt5.QtWidgets import QDateEdit, QMessageBox

from src.api.models import StudentDTO, validate_iranian_phone, validate_national_code


class StudentDialog(QDialog):
    """دیالوگ افزودن/ویرایش دانش‌آموز با اعتبارسنجی ساده."""

    def __init__(self, student: Optional[StudentDTO] = None, parent=None) -> None:
        super().__init__(parent)
        self.student = student
        self.is_edit_mode = student is not None
        self._setup_ui()
        self._populate_form()

    def _setup_ui(self) -> None:
        self.setWindowTitle("ویرایش دانش‌آموز" if self.is_edit_mode else "افزودن دانش‌آموز")
        self.setModal(True)
        self.resize(480, 560)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        self.first_name_input = QLineEdit()
        self.last_name_input = QLineEdit()
        self.national_code_input = QLineEdit()
        self.phone_input = QLineEdit()
        self.birth_date_edit = QDateEdit()
        self.birth_date_edit.setCalendarPopup(True)
        self.birth_date_edit.setDisplayFormat("yyyy/MM/dd")
        try:
            self.birth_date_edit.setLocale(QLocale(QLocale.Persian))
        except Exception:
            pass
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["زن", "مرد"])  # 0,1
        self.center_combo = QComboBox()
        self.center_combo.addItems(["مرکز", "گلستان", "صدرا"])  # 1,2,3
        self.education_status_combo = QComboBox()
        self.education_status_combo.addItems(["فارغ‌التحصیل", "درحال تحصیل"])  # 0,1
        self.level_combo = QComboBox()
        self.level_combo.addItems(["konkoori", "motavassete2", "motavassete1"])  # نمونه
        self.school_type_combo = QComboBox()
        self.school_type_combo.addItems(["عادی", "مدرسه‌ای"])  # normal, school
        self.school_code_input = QLineEdit()

        form_layout.addRow("نام:", self.first_name_input)
        form_layout.addRow("نام خانوادگی:", self.last_name_input)
        form_layout.addRow("کدملی:", self.national_code_input)
        form_layout.addRow("تلفن:", self.phone_input)
        form_layout.addRow("تاریخ تولد:", self.birth_date_edit)
        form_layout.addRow("جنسیت:", self.gender_combo)
        form_layout.addRow("مرکز:", self.center_combo)
        form_layout.addRow("وضعیت تحصیل:", self.education_status_combo)
        form_layout.addRow("مقطع:", self.level_combo)
        form_layout.addRow("نوع:", self.school_type_combo)
        form_layout.addRow("کد مدرسه:", self.school_code_input)

        layout.addLayout(form_layout)

        btns = QHBoxLayout()
        self.save_btn = QPushButton("💾 ذخیره")
        self.cancel_btn = QPushButton("❌ انصراف")
        btns.addStretch()
        btns.addWidget(self.save_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _populate_form(self) -> None:
        if not self.student:
            return
        self.first_name_input.setText(self.student.first_name)
        self.last_name_input.setText(self.student.last_name)
        self.national_code_input.setText(self.student.national_code)
        self.phone_input.setText(self.student.phone)
        # QDate from date
        bd = self.student.birth_date
        self.birth_date_edit.setDate(QDate(bd.year, bd.month, bd.day))
        self.gender_combo.setCurrentIndex(int(self.student.gender))
        self.center_combo.setCurrentIndex(int(self.student.center) - 1)
        self.education_status_combo.setCurrentIndex(int(self.student.education_status))
        self.level_combo.setCurrentText(self.student.grade_level)
        self.school_type_combo.setCurrentIndex(1 if self.student.school_type == "school" else 0)
        self.school_code_input.setText(self.student.school_code or "")

    def get_student_data(self) -> dict:
        """برگرداندن داده‌های فرم به‌عنوان دیکشنری."""
        return {
            "first_name": self.first_name_input.text().strip(),
            "last_name": self.last_name_input.text().strip(),
            "national_code": self.national_code_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "birth_date": self.birth_date_edit.date().toString("yyyy-MM-dd"),
            "gender": self.gender_combo.currentIndex(),
            "center": self.center_combo.currentIndex() + 1,
            "education_status": self.education_status_combo.currentIndex(),
            "grade_level": self.level_combo.currentText(),
            "school_type": "school" if self.school_type_combo.currentIndex() == 1 else "normal",
            "school_code": self.school_code_input.text().strip() or None,
        }

    def accept(self) -> None:  # noqa: D401
        data = self.get_student_data()
        if not data["first_name"] or not data["last_name"]:
            QMessageBox.warning(self, "اعتبارسنجی", "نام و نام خانوادگی الزامی است")
            return
        if not validate_national_code(data["national_code"]):
            QMessageBox.warning(self, "اعتبارسنجی", "کدملی نامعتبر است")
            return
        if not validate_iranian_phone(data["phone"]):
            QMessageBox.warning(self, "اعتبارسنجی", "شماره تلفن نامعتبر است")
            return
        super().accept()
