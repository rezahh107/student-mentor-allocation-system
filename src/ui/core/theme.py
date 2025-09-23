from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication


class PersianTheme:
    """پیکربندی تم راست‌به‌چپ فارسی."""

    STYLE_SHEET = """
    QMainWindow {
        background-color: #f5f5f5;
        direction: rtl;
    }

    QMenuBar {
        background-color: #2c3e50;
        color: white;
        font-family: 'Vazir', 'Tahoma';
        font-size: 12px;
        padding: 5px;
    }

    QMenuBar::item:selected {
        background-color: #34495e;
    }

    QMenu {
        font-family: 'Vazir', 'Tahoma';
        font-size: 12px;
    }

    QToolBar {
        background-color: #ecf0f1;
        border: none;
        padding: 5px;
        spacing: 10px;
    }

    QToolButton {
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 5px;
        font-family: 'Vazir', 'Tahoma';
        font-size: 11px;
    }

    QToolButton:hover {
        background-color: #dfe6e9;
        border-color: #b2bec3;
    }

    QStatusBar {
        background-color: #2c3e50;
        color: white;
        font-family: 'Vazir', 'Tahoma';
        font-size: 11px;
    }

    QPushButton {
        background-color: #3498db;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        font-family: 'Vazir', 'Tahoma';
        font-size: 12px;
    }

    QPushButton:hover {
        background-color: #2980b9;
    }

    QPushButton:pressed {
        background-color: #21618c;
    }

    QPushButton:disabled {
        background-color: #bdc3c7;
        color: #7f8c8d;
    }
    """

    @staticmethod
    def apply(app: QApplication) -> None:
        """اعمال تم روی برنامه."""
        app.setLayoutDirection(Qt.RightToLeft)
        app.setStyleSheet(PersianTheme.STYLE_SHEET)

        # تنظیم فونت پیش‌فرض با fallback
        preferred_fonts = ["Vazir", "IRANSans", "Tahoma", "Segoe UI"]
        for fname in preferred_fonts:
            font = QFont(fname, 10)
            if font.family():
                app.setFont(font)
                break

