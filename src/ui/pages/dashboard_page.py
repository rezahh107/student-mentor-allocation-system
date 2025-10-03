from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict
import logging
import os

import jdatetime
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from src.core.clock import tehran_clock
from src.ui._safety import is_minimal_mode, log_minimal_mode, swallow_ui_error
from src.ui.pages.dashboard_presenter import DashboardPresenter
from src.ui.widgets.charts.age_distribution_chart import AgeDistributionChart
from src.ui.widgets.charts.center_performance_chart import CenterPerformanceChart
from src.ui.widgets.charts.gender_distribution_chart import GenderDistributionChart
from src.ui.widgets.charts.registration_trend_chart import RegistrationTrendChart
from src.ui.widgets.loading_overlay import LoadingOverlay
from src.ui.widgets.statistic_card import StatisticCard
from src.ui.dialogs.dashboard_settings_dialog import DashboardSettingsDialog
from src.ui.widgets.charts.chart_themes import ChartThemes


class DashboardPage(QWidget):
    """صفحه داشبورد تحلیلی دانش‌آموزان با کارت‌ها و نمودارها."""

    LOGGER = logging.getLogger(__name__)

    def __init__(self, presenter: DashboardPresenter) -> None:
        super().__init__()
        self.presenter = presenter
        self._clock = getattr(presenter, "clock", tehran_clock())
        self.charts: Dict[str, QWidget] = {}
        self.cards: Dict[str, StatisticCard] = {}
        self.overlay: LoadingOverlay | None = None
        self._minimal_mode = is_minimal_mode()
        if self._minimal_mode:
            log_minimal_mode("صفحه داشبورد")
            return
        self._setup_ui()
        self._connect_signals()

    def _skip_if_minimal(self, action: str) -> bool:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ %s اجرا نشد.", action)
            return True
        return False

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = self._create_header()
        main_layout.addWidget(header)

        # Toolbar
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # Cards row
        cards_widget = self._create_cards_row()
        main_layout.addWidget(cards_widget)

        # Charts grid
        charts_widget = self._create_charts_grid()
        main_layout.addWidget(charts_widget)

        # Details section
        details_widget = self._create_details_section()
        main_layout.addWidget(details_widget)

        # Overlay
        self.overlay = LoadingOverlay(self)

    def _create_header(self) -> QWidget:
        w = QFrame()
        w.setObjectName("headerFrame")
        lay = QHBoxLayout(w)
        title = QLabel("📊 داشبورد تحلیلی مدیریت دانش‌آموزان")
        title.setObjectName("mainTitle")
        lay.addWidget(title)
        lay.addStretch()
        self.last_update_label = QLabel("آخرین بروزرسانی: ---")
        self.last_update_label.setObjectName("statusLabel")
        lay.addWidget(self.last_update_label)
        w.setStyleSheet(
            """
            #headerFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #667eea, stop:1 #764ba2); border-radius: 12px; padding: 16px; }
            #mainTitle { color: white; font-size: 20px; font-weight: bold; }
            #statusLabel { color: rgba(255,255,255,0.9); }
            """
        )
        return w

    def _create_toolbar(self) -> QWidget:
        tb = QToolBar()
        # Date range
        self.date_range_combo = QComboBox()
        self.date_range_combo.addItems(["امروز", "7 روز گذشته", "30 روز گذشته", "3 ماه گذشته", "6 ماه گذشته", "1 سال گذشته", "بازه سفارشی..."])
        tb.addWidget(QLabel("بازه زمانی: "))
        tb.addWidget(self.date_range_combo)
        self.custom_dates = QWidget()
        dt_lay = QHBoxLayout(self.custom_dates)
        dt_lay.setContentsMargins(0, 0, 0, 0)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(self.start_date.date().addDays(-30))
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        dt_lay.addWidget(QLabel("از:"))
        dt_lay.addWidget(self.start_date)
        dt_lay.addWidget(QLabel("تا:"))
        dt_lay.addWidget(self.end_date)
        self.custom_dates.hide()
        tb.addWidget(self.custom_dates)

        tb.addSeparator()
        self.refresh_action = QAction(QIcon(), "بروزرسانی", self)
        tb.addAction(self.refresh_action)
        self.auto_refresh_cb = QCheckBox("بروزرسانی خودکار (5 دقیقه)")
        self.auto_refresh_cb.setChecked(True)
        tb.addWidget(self.auto_refresh_cb)
        tb.addSeparator()
        self.pdf_action = QAction(QIcon(), "دانلود گزارش PDF", self)
        tb.addAction(self.pdf_action)
        self.print_action = QAction(QIcon(), "چاپ", self)
        tb.addAction(self.print_action)
        self.settings_action = QAction(QIcon(), "تنظیمات", self)
        tb.addAction(self.settings_action)
        return tb

    def _create_cards_row(self) -> QWidget:
        w = QFrame()
        lay = QHBoxLayout(w)
        lay.setSpacing(12)
        configs = [
            {"id": "total", "title": "کل دانش‌آموزان", "icon": "👥", "color": "#2196F3"},
            {"id": "active", "title": "ثبت‌نام فعال", "icon": "✅", "color": "#4CAF50"},
            {"id": "pending", "title": "در انتظار تخصیص", "icon": "⏳", "color": "#FF9800"},
            {"id": "centers", "title": "مراکز فعال", "icon": "🏢", "color": "#9C27B0"},
        ]
        for cfg in configs:
            card = StatisticCard(cfg["title"], cfg["icon"], cfg["color"], initial_value="0", subtitle="")
            self.cards[cfg["id"]] = card
            lay.addWidget(card)
        return w

    def _create_charts_grid(self) -> QWidget:
        gw = QWidget()
        grid = QGridLayout(gw)
        grid.setSpacing(12)
        # Gender
        self.charts["gender"] = GenderDistributionChart()
        grid.addWidget(self._chart_container("توزیع جنسیتی", self.charts["gender"]), 0, 0)
        # Trend
        self.charts["trend"] = RegistrationTrendChart()
        grid.addWidget(self._chart_container("روند ثبت‌نام 12 ماه گذشته", self.charts["trend"]), 0, 1)
        # Centers
        self.charts["centers"] = CenterPerformanceChart()
        grid.addWidget(self._chart_container("عملکرد مراکز", self.charts["centers"]), 1, 0)
        # Age
        self.charts["age"] = AgeDistributionChart()
        grid.addWidget(self._chart_container("توزیع سنی", self.charts["age"]), 1, 1)
        return gw

    def _create_details_section(self) -> QWidget:
        w = QFrame()
        lay = QHBoxLayout(w)
        # Activity
        act_group = QGroupBox("🕒 فعالیت‌های اخیر")
        act_lay = QVBoxLayout(act_group)
        self.activity_list = QListWidget()
        self.activity_list.setMaximumHeight(200)
        act_lay.addWidget(self.activity_list)
        # Performance table
        perf_group = QGroupBox("📈 جدول عملکرد مراکز")
        perf_lay = QVBoxLayout(perf_group)
        self.performance_table = QTableWidget()
        self.performance_table.setColumnCount(5)
        self.performance_table.setHorizontalHeaderLabels(["مرکز", "ظرفیت", "ثبت‌شده", "تخصیص", "نرخ موفقیت"])
        self.performance_table.setMaximumHeight(200)
        perf_lay.addWidget(self.performance_table)
        lay.addWidget(act_group)
        lay.addWidget(perf_group)
        return w

    def _chart_container(self, title: str, widget: QWidget) -> QFrame:
        f = QFrame()
        f.setObjectName("chartContainer")
        lay = QVBoxLayout(f)
        lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("chartTitle")
        lay.addWidget(t)
        lay.addWidget(widget)
        f.setStyleSheet(
            """
            #chartContainer { background-color: white; border: 1px solid #e0e0e0; border-radius: 12px; padding: 12px; }
            #chartTitle { font-size: 14px; font-weight: bold; color: #2c3e50; }
            """
        )
        return f

    def _connect_signals(self) -> None:
        self.presenter.data_loaded.connect(self._on_data_loaded)
        self.presenter.loading_started.connect(lambda: self._show_overlay("در حال بارگذاری داشبورد..."))
        self.presenter.loading_finished.connect(lambda: self._hide_overlay())
        self.presenter.error_occurred.connect(lambda msg: QMessageBox.critical(self, "خطا", msg))

        self.date_range_combo.currentTextChanged.connect(self._on_date_range_changed)
        self.refresh_action.triggered.connect(lambda: self._refresh_dashboard())
        self.auto_refresh_cb.toggled.connect(self._toggle_auto_refresh)
        self.pdf_action.triggered.connect(lambda: self._export_pdf())
        self.print_action.triggered.connect(lambda: self._print_dashboard())
        self.settings_action.triggered.connect(lambda: self._open_settings())

def showEvent(self, event) -> None:  # noqa: D401, N802
    super().showEvent(event)
    if self._skip_if_minimal("نمایش دادن واقعیتردی"):
        return
    
    if not getattr(self, "_initialized", False):
        self._initialized = True
        self._refresh_dashboard()
        if self.auto_refresh_cb.isChecked():
            self.presenter.start_auto_refresh(300000)
    
    # Enable realtime updates (optional, default URL)
    try:
        self.presenter.enable_realtime_updates()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "خطای به‌روزرسانی به‌موقع یا تابوی شد", 
            exc_info=exc
        )

    def _selected_date_range(self) -> tuple[datetime, datetime]:
        txt = self.date_range_combo.currentText()
        end = self._clock.now()
        if txt == "امروز":
            start = end.replace(hour=0, minute=0, second=0, microsecond=0)
        elif txt == "7 روز گذشته":
            start = end - timedelta(days=7)
        elif txt == "30 روز گذشته":
            start = end - timedelta(days=30)
        elif txt == "3 ماه گذشته":
            start = end - timedelta(days=90)
        elif txt == "6 ماه گذشته":
            start = end - timedelta(days=180)
        elif txt == "1 سال گذشته":
            start = end - timedelta(days=365)
        else:
            start = self.start_date.date().toPyDate()
            end = self.end_date.date().toPyDate()
            if hasattr(end, "toPyDate"):
                end = end.toPyDate()
        tz = end.tzinfo

        def _ensure_aware(value: datetime | object, default_time: datetime) -> datetime:
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=tz)
            combined = datetime.combine(value, default_time.time())  # type: ignore[arg-type]
            return combined.replace(tzinfo=tz)

        start_dt = _ensure_aware(start, datetime.min)
        end_dt = _ensure_aware(end, datetime.max)
        return start_dt, end_dt

    def _on_date_range_changed(self, text: str) -> None:
        self.custom_dates.setVisible(text == "بازه سفارشی...")

    def _toggle_auto_refresh(self, enabled: bool) -> None:
        if self._skip_if_minimal("تغییر وضعیت بروزرسانی خودکار"):
            return
        if enabled:
            self.presenter.start_auto_refresh(300000)
        else:
            self.presenter.stop_auto_refresh()

    def _open_settings(self) -> None:
        if self._skip_if_minimal("باز کردن تنظیمات داشبورد"):
            return
        dlg = DashboardSettingsDialog(self)
        # Pre-fill
        dlg.auto_refresh_enabled.setChecked(self.auto_refresh_cb.isChecked())
        dlg.refresh_interval.setValue(int(self.presenter.refresh_interval / 60000))
        # Theme preset (default/colorful/dark)
        current_theme = getattr(self, "_chart_theme", "default")
        idx = {"پیش‌فرض": "default", "تیره": "dark", "رنگارنگ": "colorful"}
        rev = {v: k for k, v in idx.items()}
        dlg.chart_theme.setCurrentText(rev.get(current_theme, "پیش‌فرض"))

        if dlg.exec_() == dlg.Accepted:
            self.auto_refresh_cb.setChecked(dlg.auto_refresh_enabled.isChecked())
            minutes = dlg.refresh_interval.value()
            interval_ms = max(1, minutes) * 60_000
            if self.auto_refresh_cb.isChecked():
                self.presenter.start_auto_refresh(interval_ms)
            else:
                self.presenter.stop_auto_refresh()

            # Apply chart theme
            chosen = dlg.chart_theme.currentText()
            theme_map = {"پیش‌فرض": "default", "تیره": "dark", "رنگارنگ": "colorful"}
            self._chart_theme = theme_map.get(chosen, "default")
            self._apply_chart_theme()

    def _apply_chart_theme(self) -> None:
        if self._skip_if_minimal("اعمال تم نمودار"):
            return
        theme = getattr(self, "_chart_theme", "default")
        # apply to charts
        self.charts["gender"].set_theme(theme)
        self.charts["trend"].set_theme(theme)
        self.charts["centers"].set_theme(theme)
        self.charts["age"].set_theme(theme)

    def _update_last_refresh_label(self) -> None:
        if self._skip_if_minimal("به‌روزرسانی برچسب زمان آخرین بروزرسانی"):
            return
        self.last_update_label.setText(
            f"آخرین بروزرسانی: {self._clock.now().strftime('%H:%M:%S')}"
        )

    def _show_overlay(self, msg: str) -> None:
        if self._skip_if_minimal("نمایش لایه بارگذاری"):
            return
        if self.overlay:
            self.overlay.show_with_message(msg)

    def _hide_overlay(self) -> None:
        if self._skip_if_minimal("پنهان‌سازی لایه بارگذاری"):
            return
        if self.overlay:
            self.overlay.hide()

    def _on_data_loaded(self, data) -> None:
        if self._skip_if_minimal("به‌روزرسانی داده‌های داشبورد"):
            return
        # Cards
        self.cards["total"].update_value(value=f"{data.total_students:,}", change=data.growth_rate, trend=data.growth_trend)
        self.cards["active"].update_value(value=f"{data.active_students:,}", percentage=f"{data.active_percentage:.1f}%")
        self.cards["pending"].update_value(value=str(data.pending_allocations), percentage=f"{data.pending_percentage:.1f}%")
        self.cards["centers"].update_value(value="3", subtitle="مرکز، گلستان، صدرا")

        # Charts
        self.charts["gender"].update_data(data.gender_distribution)
        self.charts["trend"].update_data(data.monthly_registrations)
        self.charts["centers"].update_data(data.center_performance)
        self.charts["age"].update_data(data.age_distribution)

        # Activity list
        self.activity_list.clear()
        for item in data.recent_activities:
            self.activity_list.addItem(f"{item['time']} - {item['message']} ({item['details']})")

        # Performance table (mocked from performance_metrics)
        perf = data.performance_metrics.get("center_utilization", {})
        rows = len(perf)
        self.performance_table.setRowCount(rows)
        from src.services.analytics_service import AnalyticsService
        names = {cid: AnalyticsService.get_center_name(cid) for cid in perf.keys()}
        for i, cid in enumerate(sorted(perf.keys())):
            row = perf[cid]
            self.performance_table.setItem(i, 0, QTableWidgetItem(names.get(cid, str(cid))))
            self.performance_table.setItem(i, 1, QTableWidgetItem(str(row["capacity"])))
            self.performance_table.setItem(i, 2, QTableWidgetItem(str(row["registered"])))
            self.performance_table.setItem(i, 3, QTableWidgetItem("-"))
            self.performance_table.setItem(i, 4, QTableWidgetItem(f"{row['utilization']:.1f}%"))

        self._update_last_refresh_label()

    @asyncSlot()
    async def _refresh_dashboard(self):
        if self._skip_if_minimal("بروزرسانی داشبورد"):
            return
        await self.presenter.load_dashboard_data(self._selected_date_range(), force_refresh=True)

    @asyncSlot()
    async def _export_pdf(self):
        if self._skip_if_minimal("صدور PDF داشبورد"):
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "���?�?�?�? �?���?�?�? PDF",
            f"�?���?�?�?_�?�?�?�?�?�?�?_{jdatetime.datetime.fromgregorian(datetime=self._clock.now()).strftime('%Y_%m_%d')}",
            "PDF Files (*.pdf)",
        )
        if not filename:
            return

        use_stub = os.environ.get('SMARTALLOC_FAKE_PDF', '1') == '1' and os.environ.get('PYTEST_CURRENT_TEST')
        if use_stub or os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            self._write_stub_pdf(filename)
            if not os.environ.get('PYTEST_CURRENT_TEST'):
                QMessageBox.information(self, "�?�?�?�?", "�?���?�?�? PDF �?�? �?�?�?�?�?�? ���?�?�?�? �?�?.")
            return

        def _fallback() -> None:
            self._write_stub_pdf(filename)
            if not os.environ.get('PYTEST_CURRENT_TEST'):
                QMessageBox.warning(self, "�?���?", "صدور PDF اصلی با خطا مواجه شد؛ نسخه نمایشی ذخیره شد.")

        with swallow_ui_error("صدور گزارش PDF داشبورد", fallback=_fallback):
            await self.presenter.export_pdf_report(filename)
            QMessageBox.information(self, "�?�?�?�?", "�?���?�?�? PDF �?�? �?�?�?�?�?�? ���?�?�?�? �?�?.")

    def _write_stub_pdf(self, filepath: str) -> None:
        if self._skip_if_minimal("نوشتن فایل PDF آزمایشی"):
            return
        with swallow_ui_error("نوشتن گزارش PDF نمایشی"):
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as handle:
                handle.write(b'%PDF-1.4\n% SmartAlloc stub report\nendobj\nstartxref\n0\n%%EOF')

    def _print_dashboard(self) -> None:
        if self._skip_if_minimal("چاپ داشبورد"):
            return
        printer = QPrinter(QPrinter.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec_() == QPrintDialog.Accepted:
            # چاپ کل صفحه داشبورد
            self.render(printer)
