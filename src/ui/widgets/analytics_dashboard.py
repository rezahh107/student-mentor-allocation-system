from __future__ import annotations

from typing import Dict, Optional

from src.ui.qt_optional import QtCore, QtWidgets, require_qt

require_qt()

QTimer = QtCore.QTimer
QLabel = QtWidgets.QLabel
QPushButton = QtWidgets.QPushButton
QTextEdit = QtWidgets.QTextEdit
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget

from ...services.config_manager import ConfigManager
from ...services.performance_monitor import PerformanceMonitor
from ...core.clock import SupportsNow, tehran_clock


class AnalyticsDashboard(QWidget):
    """داشبورد ساده‌ی متنی برای نمایش وضعیت تخصیص."""

    def __init__(
        self,
        *,
        performance_monitor: Optional[PerformanceMonitor] = None,
        config_manager: Optional[ConfigManager] = None,
        parent: Optional[QWidget] = None,
        clock: SupportsNow | None = None,
    ) -> None:
        super().__init__(parent)
        self.monitor = performance_monitor
        self.config = config_manager or ConfigManager()
        self._clock = clock or tehran_clock()
        self._allocation_summary: Dict[str, object] = {}
        self._last_refresh = None
        self._build_ui()
        self._setup_timer()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.title = QLabel("📊 گزارش آماری تخصیص")
        self.title.setStyleSheet("font-size: 16px; font-weight: bold; color: #2d3748;")
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.refresh_btn = QPushButton("🔄 بروزرسانی")
        self.refresh_btn.clicked.connect(self.refresh_report)
        layout.addWidget(self.title)
        layout.addWidget(self.report_text)
        layout.addWidget(self.refresh_btn)

    def _setup_timer(self) -> None:
        interval = int(self.config.get("dashboard_refresh_interval", 5000))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_report)
        self._timer.start(max(1000, interval))

    def attach_monitor(self, monitor: PerformanceMonitor) -> None:
        self.monitor = monitor

    def update_summary(self, summary: Dict[str, object]) -> None:
        self._allocation_summary = summary
        self.refresh_report()

    def refresh_report(self) -> None:
        report = self.generate_text_report()
        self.report_text.setPlainText(report)
        self._last_refresh = self._clock.now()

    def generate_text_report(self) -> str:
        stats = self.monitor.get_stats() if self.monitor else {}
        summary = self._allocation_summary
        total_students = summary.get("total_students", 0)
        successful = summary.get("successful", 0)
        failed = summary.get("failed", 0)
        centers = summary.get("centers", {})
        loads = summary.get("loads", {})

        center_lines = "\n".join(
            [f"• {name}: {count} نفر" for name, count in centers.items()]
        ) or "• اطلاعات موجود نیست"
        load_lines = "\n".join(
            [f"• {name}: {count} دانش‌آموز" for name, count in loads.items()]
        ) or "• اطلاعات موجود نیست"

        report = f"""
📊 گزارش تخصیص دانش‌آموزان
═══════════════════════════════

📈 آمار کلی:
• کل دانش‌آموزان: {total_students}
• تخصیص موفق: {successful}
• تخصیص ناموفق: {failed}

🏢 توزیع بر اساس مرکز:
{center_lines}

👥 بار کاری پشتیبان‌ها:
{load_lines}

⚡ عملکرد سیستم:
• کل تخصیص‌ها: {stats.get('total_allocations', 0)}
• میانگین زمان تخصیص: {stats.get('average_time', 0.0)} ثانیه
• نرخ موفقیت: {stats.get('success_rate', 0.0)}٪
• استفاده از حافظه: {stats.get('memory_usage', 0.0)}٪
• مدت فعالیت سیستم: {stats.get('uptime_seconds', 0)} ثانیه

🕒 آخرین بروزرسانی: {self._clock.now().strftime('%H:%M:%S')}
"""
        return report.strip()


__all__ = ["AnalyticsDashboard"]
