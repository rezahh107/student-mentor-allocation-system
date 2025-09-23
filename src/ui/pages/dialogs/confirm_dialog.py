from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class ConfirmDialog(QDialog):
    """دیالوگ تأیید عملیات حذف."""

    def __init__(self, message: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("تأیید حذف")
        self.setModal(True)
        self.resize(360, 140)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(message))

        btns = QHBoxLayout()
        self.ok_btn = QPushButton("بله، حذف شود")
        self.cancel_btn = QPushButton("انصراف")
        btns.addStretch()
        btns.addWidget(self.ok_btn)
        btns.addWidget(self.cancel_btn)
        layout.addLayout(btns)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

