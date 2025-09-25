from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Optional

from src.ui.qt_optional import QtCore, QtWidgets, require_qt

require_qt()

Signal = QtCore.Signal
QCheckBox = QtWidgets.QCheckBox
QComboBox = QtWidgets.QComboBox
QDialog = QtWidgets.QDialog
QDialogButtonBox = QtWidgets.QDialogButtonBox
QDoubleSpinBox = QtWidgets.QDoubleSpinBox
QFileDialog = QtWidgets.QFileDialog
QFormLayout = QtWidgets.QFormLayout
QHBoxLayout = QtWidgets.QHBoxLayout
QLineEdit = QtWidgets.QLineEdit
QPushButton = QtWidgets.QPushButton
QSpinBox = QtWidgets.QSpinBox
QTabWidget = QtWidgets.QTabWidget
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget

from ...services.config_manager import ConfigManager


class SettingsDialog(QDialog):
    """پنجره تنظیمات برای مانیتورینگ و داشبورد."""

    settings_changed = Signal(dict)

    def __init__(self, config_manager: ConfigManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config_manager = config_manager
        self.setWindowTitle("تنظیمات سیستم")
        self.setModal(True)
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self._allocation_tab = self._create_allocation_tab()
        tabs.addTab(self._allocation_tab, "قوانین تخصیص")
        self._performance_tab = self._create_performance_tab()
        tabs.addTab(self._performance_tab, "عملکرد")
        self._ui_tab = self._create_ui_tab()
        tabs.addTab(self._ui_tab, "رابط کاربری")
        self._export_tab = self._create_export_tab()
        tabs.addTab(self._export_tab, "خروجی")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._persist)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(540, 400)

    def _create_allocation_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.same_center_check = QCheckBox("تخصیص فقط در همان مرکز")
        self.prefer_load_check = QCheckBox("اولویت با پشتیبان کم‌بار")
        self.capacity_weight = QDoubleSpinBox()
        self.capacity_weight.setRange(0.0, 2.0)
        self.capacity_weight.setSingleStep(0.1)
        self.capacity_weight.setDecimals(2)
        self.max_concurrent = QSpinBox()
        self.max_concurrent.setRange(1, 8)
        form.addRow("قانون مرکز:", self.same_center_check)
        form.addRow("قانون بار:", self.prefer_load_check)
        form.addRow("وزن ظرفیت:", self.capacity_weight)
        form.addRow("حداکثر تخصیص همزمان:", self.max_concurrent)
        return widget

    def _create_performance_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.monitoring_enabled = QCheckBox("فعال‌سازی مانیتورینگ")
        self.auto_start_monitor = QCheckBox("شروع خودکار")
        self.sample_interval = QDoubleSpinBox()
        self.sample_interval.setRange(0.1, 10.0)
        self.sample_interval.setSingleStep(0.1)
        self.history_minutes = QSpinBox()
        self.history_minutes.setRange(1, 120)
        self.alert_cpu = QDoubleSpinBox()
        self.alert_cpu.setRange(10, 100)
        self.alert_cpu.setSuffix(" %")
        self.alert_memory = QDoubleSpinBox()
        self.alert_memory.setRange(10, 100)
        self.alert_memory.setSuffix(" %")
        self.alert_disk = QDoubleSpinBox()
        self.alert_disk.setRange(10, 100)
        self.alert_disk.setSuffix(" %")
        form.addRow("مانیتورینگ:", self.monitoring_enabled)
        form.addRow("شروع خودکار:", self.auto_start_monitor)
        form.addRow("بازه نمونه‌برداری (ثانیه):", self.sample_interval)
        form.addRow("حافظه تاریخچه (دقیقه):", self.history_minutes)
        form.addRow("آستانه CPU:", self.alert_cpu)
        form.addRow("آستانه حافظه:", self.alert_memory)
        form.addRow("آستانه دیسک:", self.alert_disk)
        return widget

    def _create_ui_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["light", "dark"])
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(250, 10000)
        self.refresh_interval.setSuffix(" ms")
        self.tooltips_check = QCheckBox("نمایش راهنما")
        self.animations_check = QCheckBox("انیمیشن‌ها")
        form.addRow("تم:", self.theme_combo)
        form.addRow("بازه به‌روزرسانی:", self.refresh_interval)
        form.addRow("نمایش Tooltips:", self.tooltips_check)
        form.addRow("انیمیشن‌ها:", self.animations_check)
        return widget

    def _create_export_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        path_layout = QHBoxLayout()
        self.export_path = QLineEdit()
        browse = QPushButton("...")
        browse.clicked.connect(self._browse_export_path)
        path_layout.addWidget(self.export_path)
        path_layout.addWidget(browse)
        self.timestamp_check = QCheckBox("افزودن زمان به نام فایل")
        self.pdf_quality = QComboBox()
        self.pdf_quality.addItems(["high", "medium", "low"])
        self.image_dpi = QSpinBox()
        self.image_dpi.setRange(72, 600)
        form.addRow("مسیر خروجی:", path_layout)
        form.addRow("افزودن زمان:", self.timestamp_check)
        form.addRow("کیفیت PDF:", self.pdf_quality)
        form.addRow("DPI تصویر:", self.image_dpi)
        return widget

    def _load_settings(self) -> None:
        cfg = self.config_manager.config
        self.same_center_check.setChecked(cfg.allocation.same_center_only)
        self.prefer_load_check.setChecked(cfg.allocation.prefer_lower_load)
        self.capacity_weight.setValue(cfg.allocation.capacity_weight)
        self.max_concurrent.setValue(cfg.allocation.max_concurrent_allocations)

        self.monitoring_enabled.setChecked(cfg.monitoring.enabled)
        self.auto_start_monitor.setChecked(cfg.monitoring.auto_start)
        self.sample_interval.setValue(cfg.performance.sample_interval)
        self.history_minutes.setValue(cfg.performance.history_minutes)
        self.alert_cpu.setValue(cfg.performance.alert_cpu_threshold)
        self.alert_memory.setValue(cfg.performance.alert_memory_threshold)
        self.alert_disk.setValue(cfg.performance.alert_disk_threshold)

        self.theme_combo.setCurrentText(cfg.ui.theme)
        self.refresh_interval.setValue(cfg.ui.refresh_interval_ms)
        self.tooltips_check.setChecked(cfg.ui.show_tooltips)
        self.animations_check.setChecked(cfg.ui.animations_enabled)

        self.export_path.setText(cfg.export.default_directory)
        self.timestamp_check.setChecked(cfg.export.include_timestamp)
        self.pdf_quality.setCurrentText(cfg.export.pdf_quality)
        self.image_dpi.setValue(cfg.export.image_dpi)

    def _persist(self) -> None:
        updates: Dict[str, Any] = {}
        updates.update(
            {
                "allocation.same_center_only": self.same_center_check.isChecked(),
                "allocation.prefer_lower_load": self.prefer_load_check.isChecked(),
                "allocation.capacity_weight": self.capacity_weight.value(),
                "allocation.max_concurrent_allocations": self.max_concurrent.value(),
                "monitoring.enabled": self.monitoring_enabled.isChecked(),
                "monitoring.auto_start": self.auto_start_monitor.isChecked(),
                "performance.sample_interval": self.sample_interval.value(),
                "performance.history_minutes": self.history_minutes.value(),
                "performance.alert_cpu_threshold": self.alert_cpu.value(),
                "performance.alert_memory_threshold": self.alert_memory.value(),
                "performance.alert_disk_threshold": self.alert_disk.value(),
                "ui.theme": self.theme_combo.currentText(),
                "ui.refresh_interval_ms": self.refresh_interval.value(),
                "ui.show_tooltips": self.tooltips_check.isChecked(),
                "ui.animations_enabled": self.animations_check.isChecked(),
                "export.default_directory": self.export_path.text(),
                "export.include_timestamp": self.timestamp_check.isChecked(),
                "export.pdf_quality": self.pdf_quality.currentText(),
                "export.image_dpi": self.image_dpi.value(),
            }
        )
        for path, value in updates.items():
            self.config_manager.set(path, value, persist=False)
        self.config_manager.save()
        self.settings_changed.emit(self.config_manager.to_dict())
        self.accept()

    def _browse_export_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "انتخاب مسیر خروجی", self.export_path.text())
        if path:
            self.export_path.setText(path)


__all__ = ["SettingsDialog"]
