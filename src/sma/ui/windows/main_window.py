from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QProgressBar,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)
from qasync import asyncSlot

from sma.ui.core.app_state import AppState
from sma.ui.core.theme import PersianTheme
from sma.ui.presenters.main_presenter import MainPresenter
from sma.ui.utils.error_handler import ErrorHandler
from sma.ui.widgets.loading_overlay import LoadingOverlay
from sma.ui._safety import swallow_ui_error


LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """پنجره اصلی برنامه با پشتیبانی async.

    قابلیت‌ها:
    - چیدمان RTL با فونت فارسی
    - اکشن‌های منو آگاه از async
    - ابزار ناوبری و صفحات مرکزی
    - نوار وضعیت با وضعیت اتصال
    - اورلی بارگذاری برای عملیات async
    - مدیریت خطای مرکزی
    """

    def __init__(self, presenter: MainPresenter):
        super().__init__()
        self.presenter = presenter
        self._error_handler = ErrorHandler(self)

        self._central_stack: Optional[QStackedWidget] = None
        self._overlay: Optional[LoadingOverlay] = None
        self._status_connection: Optional[QLabel] = None
        self._status_last_update: Optional[QLabel] = None
        self._status_user: Optional[QLabel] = None
        self._status_progress: Optional[QProgressBar] = None

        self._setup_ui()
        self._setup_async_connections()
        self._apply_theme()

    # ---------------- UI setup ----------------
    def _setup_ui(self) -> None:
        self.setWindowTitle("سیستم تخصیص منتور")
        self.setMinimumSize(1100, 700)

        # منوبار
        self._create_menu_bar()

        # نوار ابزار
        self._create_toolbar()

        # مرکز صفحات
        self._central_stack = QStackedWidget(self)
        self.setCentralWidget(self._central_stack)
        self._create_pages()

        # اورلی بارگذاری
        self._overlay = LoadingOverlay(self.centralWidget())

        # وضعیت
        self._create_status_bar()

    def _create_menu_bar(self) -> None:
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)

        # فایل
        file_menu = menubar.addMenu("&فایل")
        settings_act = QAction("تنظیمات", self)
        settings_act.setShortcut("Ctrl+,")
        settings_act.triggered.connect(self.show_settings)
        exit_act = QAction("خروج", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(settings_act)
        file_menu.addSeparator()
        file_menu.addAction(exit_act)

        # دانش‌آموزان
        students_menu = menubar.addMenu("&دانش‌آموزان")
        students_list_act = QAction("لیست دانش‌آموزان", self)
        students_list_act.setShortcut("Ctrl+S")
        students_list_act.triggered.connect(self.show_students)
        student_add_act = QAction("افزودن دانش‌آموز", self)
        student_add_act.setShortcut("Ctrl+N")
        student_import_act = QAction("ورود گروهی", self)
        student_import_act.setShortcut("Ctrl+I")
        # Placeholders
        student_add_act.triggered.connect(lambda: self.show_status("افزودن دانش‌آموز (در دست توسعه)"))
        student_import_act.triggered.connect(lambda: self.show_status("ورود گروهی (در دست توسعه)"))
        students_menu.addActions([students_list_act, student_add_act, student_import_act])

        # منتورها
        mentors_menu = menubar.addMenu("&منتورها")
        mentors_list_act = QAction("لیست منتورها", self)
        mentors_list_act.setShortcut("Ctrl+M")
        mentors_list_act.triggered.connect(self.show_mentors)
        capacity_act = QAction("مدیریت ظرفیت", self)
        performance_act = QAction("گزارش عملکرد", self)
        capacity_act.triggered.connect(lambda: self.show_status("مدیریت ظرفیت (در دست توسعه)"))
        performance_act.triggered.connect(lambda: self.show_status("گزارش عملکرد (در دست توسعه)"))
        mentors_menu.addActions([mentors_list_act, capacity_act, performance_act])

        # تخصیص
        alloc_menu = menubar.addMenu("&تخصیص")
        auto_act = QAction("تخصیص خودکار", self)
        auto_act.setShortcut("F5")
        auto_act.triggered.connect(self.auto_allocate)
        manual_act = QAction("مدیریت دستی", self)
        review_act = QAction("بازبینی موارد معلق", self)
        manual_act.triggered.connect(lambda: self.show_status("مدیریت دستی (در دست توسعه)"))
        review_act.triggered.connect(lambda: self.show_status("بازبینی موارد معلق (در دست توسعه)"))
        alloc_menu.addActions([auto_act, manual_act, review_act])

        # گزارش‌ها
        reports_menu = menubar.addMenu("&گزارش‌ها")
        dashboard_act = QAction("داشبورد", self)
        dashboard_act.setShortcut("Ctrl+D")
        dashboard_act.triggered.connect(self.show_dashboard)
        reports_alloc_act = QAction("گزارش تخصیص‌ها", self)
        export_excel_act = QAction("خروجی Excel", self)
        reports_alloc_act.triggered.connect(lambda: self.show_status("گزارش تخصیص‌ها (در دست توسعه)"))
        export_excel_act.triggered.connect(lambda: self.show_status("خروجی Excel (در دست توسعه)"))
        reports_menu.addActions([dashboard_act, reports_alloc_act, export_excel_act])

        # راهنما
        help_menu = menubar.addMenu("&راهنما")
        help_act = QAction("راهنمای استفاده", self)
        help_act.setShortcut("F1")
        about_act = QAction("درباره برنامه", self)
        help_act.triggered.connect(lambda: self.show_status("راهنما (در دست توسعه)"))
        about_act.triggered.connect(lambda: self.show_status("سیستم تخصیص منتور نسخه ۱.۰"))
        help_menu.addActions([help_act, about_act])

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("ابزارها", self)
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        toolbar_actions = [
            ("dashboard", "نمایش داشبورد", "icons/dashboard.svg", self.show_dashboard),
            ("students", "دانش‌آموزان", "icons/students.svg", self.show_students),
            ("mentors", "منتورها", "icons/mentors.svg", self.show_mentors),
            ("allocate", "تخصیص خودکار", "icons/allocate.svg", self.auto_allocate),
            ("separator", None, None, None),
            ("refresh", "بروزرسانی", "icons/refresh.svg", self.refresh_data),
            ("settings", "تنظیمات", "icons/settings.svg", self.show_settings),
        ]

        for key, text, icon_path, handler in toolbar_actions:
            if key == "separator":
                toolbar.addSeparator()
                continue
            action = QAction(QIcon(icon_path) if icon_path else QIcon(), text or "", self)
            if handler is not None:
                action.triggered.connect(handler)  # type: ignore[arg-type]
            toolbar.addAction(action)

    def _create_pages(self) -> None:
        if self._central_stack is None:
LOGGER.error("مشکل در تنفیذ امنیت و پیاده‌سازی QStackedWidget - عدم توانایی تنفیذ امنت UI بسته مرکزی")
raise RuntimeError("عدم توانایی تنفیذ امنت UI بسته مرکزی")
        # صفحات placeholder
        from sma.ui.pages.dashboard_page import DashboardPage
        from sma.ui.pages.dashboard_presenter import DashboardPresenter
        self._page_dashboard = DashboardPage(DashboardPresenter(self.presenter.api_client))

        from sma.ui.pages.students_page import StudentsPage
        self._page_students = StudentsPage(self.presenter.api_client, self.presenter.event_bus)

        self._page_mentors = QLabel("لیست منتورها", self)
        self._page_mentors.setAlignment(Qt.AlignCenter)

        self._central_stack.addWidget(self._page_dashboard)
        self._central_stack.addWidget(self._page_students)
        self._central_stack.addWidget(self._page_mentors)
        self._central_stack.setCurrentWidget(self._page_dashboard)

    def _create_status_bar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)

        self._status_connection = QLabel("🔴 حالت آفلاین (Mock)")
        self._status_last_update = QLabel("آخرین بروزرسانی: -")
        self._status_user = QLabel("کاربر: مدیر سیستم")

        self._status_progress = QProgressBar(self)
        self._status_progress.setFixedWidth(180)
        self._status_progress.setRange(0, 0)  # نامحدود
        self._status_progress.hide()

        status.addPermanentWidget(self._status_connection)
        status.addPermanentWidget(self._status_last_update)
        status.addPermanentWidget(self._status_user)
        status.addPermanentWidget(self._status_progress)

        # مقدار اولیه وضعیت اتصال
        mode = self.presenter.state.api_mode
        self._update_connection_status(mode)

    # ---------------- connections & theme ----------------
    def _setup_async_connections(self) -> None:
        # رویدادهای Presenter
        self.presenter.event_bus.subscribe("loading_start", self._on_loading_start)
        self.presenter.event_bus.subscribe("loading_end", self._on_loading_end)
        self.presenter.event_bus.subscribe("data_updated", self._on_data_updated)
        self.presenter.event_bus.subscribe("api_mode_changed", self._on_api_mode_changed)
        self.presenter.event_bus.subscribe("error", self._on_error)
        self.presenter.event_bus.subscribe("success", self._on_success)

        # شروع Initialization در پس‌زمینه
        asyncio.create_task(self.presenter.initialize())

    def _apply_theme(self) -> None:
        PersianTheme.apply(QApplication.instance())

    # ---------------- event handlers ----------------
    def resizeEvent(self, event) -> None:  # noqa: D401, N802
        super().resizeEvent(event)
        if self._overlay and self.centralWidget():
            self._overlay.resize(self.centralWidget().size())

    async def _on_loading_start(self, message: str) -> None:
        if self._overlay:
            self._overlay.show_with_message(message or "در حال پردازش...")
        if self._status_progress:
            self._status_progress.show()

    async def _on_loading_end(self, _=None) -> None:  # noqa: ANN001
        if self._overlay:
            self._overlay.hide()
        if self._status_progress:
            self._status_progress.hide()

    async def _on_data_updated(self, state: AppState) -> None:
        # بروزرسانی برچسب ها
        if self._status_last_update:
            ts = state.last_update.strftime("%H:%M:%S") if state.last_update else "-"
            self._status_last_update.setText(f"آخرین بروزرسانی: {ts}")
        # Placeholder به‌روزرسانی متن صفحات
        # اگر صفحه دانش‌آموزان لیبل نیست، از بروزرسانی مستقیم متن صرف‌نظر می‌کنیم
try:
    self._page_students.setText(f"تعداد {len(state.students)} لیست دانشآموزان")  # type: ignore[call-arg]
except Exception as exc:  # noqa: BLE001
    logging.getLogger(__name__).warning("بروزرسانی شمار دانشآموزان شکست خورد", exc_info=exc)
        self._page_mentors.setText(f"لیست منتورها (تعداد: {len(state.mentors)})")
        if state.stats:
            self._page_dashboard.setText(
                "داشبورد\n"
                f"دانش‌آموزان: {state.stats.total_students}\n"
                f"منتورها: {state.stats.total_mentors}\n"
                f"تخصیص‌ها: {state.stats.total_allocations}\n"
                f"موفقیت: {state.stats.allocation_success_rate}%\n"
                f"استفاده ظرفیت: {state.stats.capacity_utilization}%"
            )

    async def _on_api_mode_changed(self, mode: str) -> None:
        self._update_connection_status(mode)

    async def _on_error(self, error) -> None:  # noqa: D401, ANN001
        if isinstance(error, Exception):
            self._error_handler.handle_error(error, context="MainPresenter")
        else:
            self._error_handler.handle_error(Exception(str(error)), context="MainPresenter")

    async def _on_success(self, message: str) -> None:
        if message:
            self.show_status(str(message))

    def _update_connection_status(self, mode: str) -> None:
        if not self._status_connection:
            return
        if mode == "real":
            self._status_connection.setText("🟢 متصل به سرور")
        else:
            self._status_connection.setText("🔴 حالت آفلاین (Mock)")

    # ---------------- navigation & actions ----------------
    def show_status(self, text: str) -> None:
        self.statusBar().showMessage(text, 5000)

    def show_dashboard(self) -> None:
        if self._central_stack is None:
LOGGER.error("مرکزی فعال‌سازی نشده - گزینه متحده برای نمایش داشبورد آماده نیست")
raise RuntimeError("گزینه متحده برای نمایش داشبورد آماده نیست")
        self._central_stack.setCurrentWidget(self._page_dashboard)
        self.presenter.state.current_page = "dashboard"

    def show_students(self) -> None:
        if self._central_stack is None:
LOGGER.error(
            "مرورگر فایل آپلودی نشده است؛ صفحه «دانش‌آموزان» نمایش داده نشد"
        )
        return
        self._central_stack.setCurrentWidget(self._page_students)
        self.presenter.state.current_page = "students"

    def show_mentors(self) -> None:
        if self._central_stack is None:
LOGGER.error(
            "مرورگر فایل آپلودی نشده است؛ صفحه «دانش‌آموزان» نمایش داده نشد"
        )
        return
        self._central_stack.setCurrentWidget(self._page_mentors)
        self.presenter.state.current_page = "mentors"

    def show_settings(self) -> None:
        self.show_status("تنظیمات (در دست توسعه)")

    @asyncSlot()
    async def refresh_data(self) -> None:
        """اجرای بروزرسانی داده‌ها به صورت async."""
        try:
            await self.presenter.refresh_all_data()
            self.show_status("✅ بروزرسانی با موفقیت انجام شد")
        except Exception as e:  # noqa: BLE001
            self._error_handler.handle_error(e, context="Refresh Data")

    @asyncSlot()
    async def auto_allocate(self) -> None:
        """Placeholder برای تخصیص خودکار (نمایشی)."""
        try:
            await self.presenter.refresh_all_data()
            self.show_status("الگوریتم تخصیص خودکار در دست توسعه است")
        except Exception as e:  # noqa: BLE001
            self._error_handler.handle_error(e, context="Auto Allocate")
