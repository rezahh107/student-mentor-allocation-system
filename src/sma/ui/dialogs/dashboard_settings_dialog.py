from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
)


class DashboardSettingsDialog(QDialog):
    """دیالوگ تنظیمات داشبورد (بروزرسانی خودکار، تم نمودار، خروجی)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("تنظیمات داشبورد")
        self.setModal(True)
        self.resize(420, 320)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Auto-refresh
        refresh_group = QGroupBox("بروزرسانی خودکار")
        refresh_layout = QFormLayout(refresh_group)
        self.auto_refresh_enabled = QCheckBox("فعال‌سازی بروزرسانی خودکار")
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(1, 60)
        self.refresh_interval.setValue(5)
        self.refresh_interval.setSuffix(" دقیقه")
        refresh_layout.addRow("وضعیت:", self.auto_refresh_enabled)
        refresh_layout.addRow("بازه زمانی:", self.refresh_interval)
        layout.addWidget(refresh_group)

        # Charts
        chart_group = QGroupBox("تنظیمات نمودارها")
        chart_layout = QFormLayout(chart_group)
        self.chart_theme = QComboBox()
        self.chart_theme.addItems(["پیش‌فرض", "تیره", "رنگارنگ"])  # Placeholder
        self.show_values = QCheckBox("نمایش مقادیر روی نمودارها")
        self.show_values.setChecked(True)
        chart_layout.addRow("تم نمودارها:", self.chart_theme)
        chart_layout.addRow("نمایش مقادیر:", self.show_values)
        layout.addWidget(chart_group)

        # Export
        export_group = QGroupBox("تنظیمات خروجی")
        export_layout = QFormLayout(export_group)
        self.pdf_quality = QComboBox()
        self.pdf_quality.addItems(["استاندارد", "بالا", "فوق‌العاده"])  # Placeholder
        self.include_charts = QCheckBox("شامل نمودارها در PDF")
        self.include_charts.setChecked(True)
        export_layout.addRow("کیفیت PDF:", self.pdf_quality)
        export_layout.addRow("نمودارها:", self.include_charts)
        layout.addWidget(export_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

