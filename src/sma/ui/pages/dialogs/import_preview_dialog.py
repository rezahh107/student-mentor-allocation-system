from __future__ import annotations

from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from sma.services.excel_import_service import ImportValidationResult


class ImportPreviewDialog(QDialog):
    """پیش‌نمایش نتایج اعتبارسنجی فایل ورودی اکسل."""

    def __init__(self, validation_result: ImportValidationResult, parent=None) -> None:
        super().__init__(parent)
        self.validation_result = validation_result
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("پیش‌نمایش ورود اطلاعات")
        self.setModal(True)
        self.resize(1000, 600)

        layout = QVBoxLayout(self)
        summary = QLabel(
            f"تعداد کل: {self.validation_result.total_rows}\n"
            f"معتبر: {len(self.validation_result.valid_rows)}\n"
            f"نامعتبر: {len(self.validation_result.invalid_rows)}"
        )
        layout.addWidget(summary)

        tabs = QTabWidget(self)
        valid_table = self._create_valid_table()
        tabs.addTab(valid_table, f"معتبر ({len(self.validation_result.valid_rows)})")
        if self.validation_result.invalid_rows:
            invalid_table = self._create_invalid_table()
            tabs.addTab(invalid_table, f"نامعتبر ({len(self.validation_result.invalid_rows)})")
        layout.addWidget(tabs)

        btns = QHBoxLayout()
        self.import_btn = QPushButton("ورود اطلاعات معتبر")
        self.import_btn.setEnabled(len(self.validation_result.valid_rows) > 0)
        self.cancel_btn = QPushButton("انصراف")
        self.cancel_btn.clicked.connect(self.reject)
        self.import_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.import_btn)
        layout.addLayout(btns)

    def _create_valid_table(self) -> QTableWidget:
        tbl = QTableWidget(self)
        cols = [
            "ردیف فایل",
            "نام",
            "نام خانوادگی",
            "کدملی",
            "تلفن",
            "تاریخ تولد",
        ]
        tbl.setColumnCount(len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.setRowCount(len(self.validation_result.valid_rows))
        for i, row in enumerate(self.validation_result.valid_rows):
            d = row["data"]
            tbl.setItem(i, 0, QTableWidgetItem(str(row["row_number"])))
            tbl.setItem(i, 1, QTableWidgetItem(str(d.get("first_name", ""))))
            tbl.setItem(i, 2, QTableWidgetItem(str(d.get("last_name", ""))))
            tbl.setItem(i, 3, QTableWidgetItem(str(d.get("national_code", ""))))
            tbl.setItem(i, 4, QTableWidgetItem(str(d.get("phone", ""))))
            tbl.setItem(i, 5, QTableWidgetItem(str(d.get("birth_date", ""))))
        tbl.resizeColumnsToContents()
        return tbl

    def _create_invalid_table(self) -> QTableWidget:
        tbl = QTableWidget(self)
        cols = ["ردیف فایل", "ارورها"]
        tbl.setColumnCount(len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.setRowCount(len(self.validation_result.invalid_rows))
        for i, row in enumerate(self.validation_result.invalid_rows):
            errs: List[str] = row.get("errors", [])
            tbl.setItem(i, 0, QTableWidgetItem(str(row.get("row_number", ""))))
            tbl.setItem(i, 1, QTableWidgetItem("؛ ".join(errs)))
        tbl.resizeColumnsToContents()
        return tbl
