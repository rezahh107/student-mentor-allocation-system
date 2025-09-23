from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
)


class ExportProgressDialog(QDialog):
    """دیالوگ پیشرفت عملیات خروجی اکسل."""

    def __init__(self, total_rows: int, parent=None) -> None:
        super().__init__(parent)
        self.total_rows = max(0, total_rows)
        self._cancelled = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("در حال صادرات به اکسل")
        self.setModal(True)
        self.resize(420, 160)

        layout = QVBoxLayout(self)
        self.label = QLabel("در حال پردازش...")
        layout.addWidget(self.label)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, self.total_rows or 0)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        btns = QHBoxLayout()
        self.cancel_btn = QPushButton("لغو")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btns.addStretch()
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

    def _on_cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def update_progress(self, done: int, total: Optional[int] = None) -> None:
        if total is not None and total != self.total_rows:
            self.total_rows = total
            self.bar.setRange(0, self.total_rows)
        self.bar.setValue(min(done, self.total_rows))
        self.label.setText(f"پیشرفت: {done} از {self.total_rows}")


class ImportProgressDialog(QDialog):
    """دیالوگ پیشرفت عملیات ورود اکسل (اعتبارسنجی و ورود)."""

    def __init__(self, title: str, total_rows: int, parent=None) -> None:
        super().__init__(parent)
        self.total_rows = max(0, total_rows)
        self._cancelled = False
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(500, 200)

        layout = QVBoxLayout(self)
        self.label = QLabel("در حال پردازش...")
        layout.addWidget(self.label)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, self.total_rows or 0)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

        btns = QHBoxLayout()
        self.cancel_btn = QPushButton("لغو")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btns.addStretch()
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

    def _on_cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def update_progress(self, done: int, total: Optional[int] = None, phase: str = "") -> None:
        if total is not None and total != self.total_rows:
            self.total_rows = total
            self.bar.setRange(0, self.total_rows)
        self.bar.setValue(min(done, self.total_rows))
        txt = f"{phase} - پیشرفت: {done} از {self.total_rows}" if phase else f"پیشرفت: {done} از {self.total_rows}"
        self.label.setText(txt)

