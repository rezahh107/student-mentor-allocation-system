from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Awaitable, Dict, List, Optional

from sma.ui.qt_optional import QtCore, QtWidgets, require_qt

require_qt()

Qt = QtCore.Qt
Signal = QtCore.Signal
QCheckBox = QtWidgets.QCheckBox
QFileDialog = QtWidgets.QFileDialog
QGridLayout = QtWidgets.QGridLayout
QGroupBox = QtWidgets.QGroupBox
QHBoxLayout = QtWidgets.QHBoxLayout
QLabel = QtWidgets.QLabel
QMessageBox = QtWidgets.QMessageBox
QPushButton = QtWidgets.QPushButton
QTabWidget = QtWidgets.QTabWidget
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget

from ...core.allocation_engine import AllocationEngine
from ...core.models import Mentor, Student
from ..widgets.analytics_dashboard import AnalyticsDashboard
from ..components.base_page import BasePage
from ...services.config_manager import ConfigManager
from ...services.performance_monitor import PerformanceMonitor
from .._safety import is_minimal_mode, log_minimal_mode, swallow_ui_error
from .allocation_presenter import AllocationPresenter


class ToggleCheckBox(QCheckBox):
    """Deterministic toggle checkbox that works in headless tests."""

    def mouseReleaseEvent(self, event):  # noqa: D401, ANN001
        if event and event.button() == Qt.LeftButton and self.isEnabled():
            if self.rect().contains(event.pos()):
                self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AllocationPage(BasePage):
    """   ԝ"""

    allocation_started = Signal()
    allocation_finished = Signal(dict)
    allocation_progress = Signal(int)
    LOGGER = logging.getLogger(__name__)

    def __init__(
        self,
        backend_service=None,
        presenter: Optional[AllocationPresenter] = None,
    ) -> None:
        super().__init__()
        self.allocation_engine = AllocationEngine()
        self.presenter = presenter or AllocationPresenter(backend_service, self.allocation_engine)

        self.config_manager = ConfigManager()
        self.performance_monitor = PerformanceMonitor()
        self.analytics_dashboard: Optional[AnalyticsDashboard] = None

        if hasattr(self.presenter, "performance_monitor"):
            self.presenter.performance_monitor = self.performance_monitor

        self.last_results: Optional[Dict[str, object]] = None
        self._last_students: List[Student] = []
        self._last_mentors: List[Mentor] = []

        self._minimal_mode = is_minimal_mode()
        if self._minimal_mode:
            log_minimal_mode("صفحه تخصیص")
            return

        self.setup_ui()
        self._apply_config_defaults()
        self._bind_presenter()
        self.load_statistics()

        if self.parent() is None:
            # Ensure the widget can receive events in tests without polluting the screen.
            self.setAttribute(Qt.WA_DontShowOnScreen, True)
            self.show()

    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("allocationTabs")

        allocation_tab = self._build_allocation_tab()
        self.tab_widget.addTab(allocation_tab, "Allocation")

        if self.presenter:
            self.analytics_dashboard = AnalyticsDashboard(
                presenter=self.presenter,
                performance_monitor=self.performance_monitor,
                config_manager=self.config_manager,
            )
            self.tab_widget.addTab(self.analytics_dashboard, "Analytics")
            self.run_async(self.analytics_dashboard.refresh_analytics())

        layout.addWidget(self.tab_widget)

    def _build_allocation_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(20)

        title = QLabel("?? ???? ????? ??????????")
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        layout.addWidget(self.create_statistics_group())
        layout.addWidget(self.create_settings_group())
        layout.addLayout(self.create_action_buttons())
        layout.addWidget(self.create_results_group())
        layout.addStretch()
        return widget

    def _apply_config_defaults(self) -> None:
        self.same_center_only.setChecked(bool(self.config_manager.get('same_center_only', True)))
        self.prefer_lower_load.setChecked(bool(self.config_manager.get('prefer_lower_load', True)))

    def create_statistics_group(self) -> QGroupBox:
        group = QGroupBox("??  ")
        grid = QGridLayout(group)

        self.students_count_label = QLabel("0")
        self.mentors_count_label = QLabel("0")
        self.total_capacity_label = QLabel("0")
        self.available_capacity_label = QLabel("0")

        grid.addWidget(QLabel("ԝ:"), 0, 0)
        grid.addWidget(self.students_count_label, 0, 1)
        grid.addWidget(QLabel(":"), 0, 2)
        grid.addWidget(self.mentors_count_label, 0, 3)

        grid.addWidget(QLabel(" :"), 1, 0)
        grid.addWidget(self.total_capacity_label, 1, 1)
        grid.addWidget(QLabel(" :"), 1, 2)
        grid.addWidget(self.available_capacity_label, 1, 3)

        return group

    def create_settings_group(self) -> QGroupBox:
        group = QGroupBox("???  ")
        box = QVBoxLayout(group)

        self.same_center_only = ToggleCheckBox("  ј")
        self.same_center_only.setChecked(True)

        self.prefer_lower_load = ToggleCheckBox("  ")
        self.prefer_lower_load.setChecked(True)

        box.addWidget(self.same_center_only)
        box.addWidget(self.prefer_lower_load)
        return group

    def create_action_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self.start_button = QPushButton("??  ")
        self.start_button.setStyleSheet(
            """
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
            """
        )
        self.start_button.clicked.connect(self._on_start_clicked)

        self.view_results_button = QPushButton("??  ")
        self.view_results_button.setEnabled(False)
        self.view_results_button.clicked.connect(self.show_detailed_results)

        row.addWidget(self.start_button)
        row.addWidget(self.view_results_button)
        row.addStretch()
        return row

    def create_results_group(self) -> QGroupBox:
        group = QGroupBox("??   ")
        box = QVBoxLayout(group)

        self.results_summary = QLabel("   ")
        self.results_summary.setStyleSheet(
            "padding: 10px; background-color: #f5f5f5; border-radius: 3px;"
        )
        box.addWidget(self.results_summary)

        buttons_row = QHBoxLayout()
        self.export_excel_button = QPushButton("??  Excel")
        self.export_excel_button.setEnabled(False)
        self.export_excel_button.clicked.connect(self._on_export_clicked)

        self.show_errors_button = QPushButton("??  ")
        self.show_errors_button.setEnabled(False)
        self.show_errors_button.clicked.connect(self.show_allocation_errors)

        buttons_row.addWidget(self.export_excel_button)
        buttons_row.addWidget(self.show_errors_button)
        buttons_row.addStretch()
        box.addLayout(buttons_row)
        return group

    # ------------------------------------------------------------------
    # Presenter wiring
    # ------------------------------------------------------------------
    def _bind_presenter(self) -> None:
        self.presenter.statistics_ready.connect(self.update_statistics_display)
        self.presenter.allocation_completed.connect(self._handle_allocation_completed)
        self.presenter.backend_error.connect(self._handle_backend_error)

    def set_presenter(self, presenter: AllocationPresenter) -> None:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ اتصال مجدد ارائه‌دهنده انجام نشد.")
            self.presenter = presenter
            return
        previous = getattr(self, "presenter", None)
        if previous is not None:
            with swallow_ui_error("قطع اتصال سیگنال‌های ارائه‌دهنده تخصیص"):
                previous.statistics_ready.disconnect(self.update_statistics_display)
                previous.allocation_completed.disconnect(self._handle_allocation_completed)
                previous.backend_error.disconnect(self._handle_backend_error)
        self.presenter = presenter
        self._bind_presenter()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def load_statistics(self) -> Optional[Awaitable]:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ بارگذاری آمار انجام نشد.")
            return None
        return self.run_async(self.presenter.load_statistics())

    async def start_allocation(self) -> None:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ فرآیند تخصیص اجرا نشد.")
            return
        metrics_students = 0
        metrics_success = 0
        duration = 0.0
        start_time = time.perf_counter()
        try:
            self.start_button.setEnabled(False)
            self.start_button.setText("? ?? ??? ?????...")
            self.allocation_started.emit()

            filters: Dict = {}
            same_center = self.same_center_only.isChecked()
            prefer_lower_load = self.prefer_lower_load.isChecked()

            self.config_manager.set('same_center_only', same_center)
            self.config_manager.set('prefer_lower_load', prefer_lower_load)
            capacity_weight = 10 if prefer_lower_load else 0

            allocation = await self.presenter.allocate_students(
                same_center_only=same_center,
                prefer_lower_load=prefer_lower_load,
                filters=filters,
                capacity_weight=capacity_weight,
            )
            students: List[Student] = allocation.get("students", [])
            mentors: List[Mentor] = allocation.get("mentors", [])
            results: Dict[str, object] = allocation.get("results", {})

            skip_notifications = False
            if not students:
                QMessageBox.information(self, "????", "???????? ???? ?????? ??? ?!")
                skip_notifications = True
            elif not mentors:
                QMessageBox.warning(self, "??", "??????? ???? ??? ?!")
                skip_notifications = True
            else:
                if results.get("assignments"):
                    await self.presenter.persist_results(results)
                self.last_results = results
                self._last_students = students
                self._last_mentors = mentors
                if "stats" in allocation:
                    self.update_statistics_display(allocation["stats"])  # type: ignore[arg-type]
                metrics_students = len(students)
                metrics_success = int(results.get("successful", 0))
                center_counts = {}
                for assignment in results.get("assignments", []):
                    mentor_id = assignment.get("mentor_id")
                    if mentor_id is None:
                        continue
                    mentor = next((m for m in mentors if getattr(m, 'id', None) == mentor_id), None)
                    if mentor:
                        key = str(getattr(mentor, 'center_id', mentor_id))
                        center_counts[key] = center_counts.get(key, 0) + 1
                load_map = {
                    (mentor.name or f"#{getattr(mentor, 'id', 0)}"): getattr(mentor, 'current_students', 0)
                    for mentor in mentors
                }
                if self.analytics_dashboard:
                    self.analytics_dashboard.update_allocation_distribution(center_counts)
                    self.analytics_dashboard.update_load_balance(load_map)
                    success_rate = (metrics_success / metrics_students * 100.0) if metrics_students else 0.0
                    self.analytics_dashboard.update_success_rate(success_rate)

            self.update_results_display(results)

            if not skip_notifications:
                self.allocation_finished.emit(results)
                self.allocation_progress.emit(100)
                QMessageBox.information(
                    self,
                    "????? ?????",
                    f"? ????: {results.get('successful', 0)}\n? ?????: {results.get('failed', 0)}",
                )
                if self.analytics_dashboard:
                    await self.analytics_dashboard.refresh_analytics()

            duration = time.perf_counter() - start_time
        except Exception as exc:  # noqa: BLE001
            duration = time.perf_counter() - start_time
            QMessageBox.critical(self, "??", f"?? ?? ??? ?????:\n{exc}")
        finally:
            self.start_button.setEnabled(True)
            self.start_button.setText("?? ???? ?????")

        if metrics_students > 0 and self.performance_monitor:
            queue_size = max(0, metrics_students - metrics_success)
            pending_jobs = max(0, metrics_students - metrics_success)
            self.performance_monitor.record_allocation(
                duration=duration,
                student_count=metrics_students,
                success_count=metrics_success,
                queue_size=queue_size,
                pending_jobs=pending_jobs,
            )
            if self.analytics_dashboard:
                history = self.performance_monitor.allocation_history()
                if history:
                    self.analytics_dashboard.append_allocation_snapshot(history[-1])

def closeEvent(self, event):  # noqa: D401, ANH001
    if self.__minimal_mode == False:
        self.LOGGER.info("پیشنهاد فعال آمدن روی‌داد پیمان مفید تعمیمی فقط ثبت شد UI حالت.")
        super().closeEvent(event)
        return
    
    if self.performance_monitor:
        try:
            self.performance_monitor.stop_monitoring()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "خطای مانیتورینگ تعمیمی یا خطا رویت کرد", 
                exc_info=exc
            )
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI updates
    # ------------------------------------------------------------------
    def update_results_display(self, results: Dict[str, object]) -> None:
        successful = int(results.get("successful", 0))
        failed = int(results.get("failed", 0))
        summary = f"? : {successful} | ? : {failed}"
        errors = results.get("errors") or []
        if failed > 0:
            summary += f"\n?? {len(errors)}   "
        self.results_summary.setText(summary)

        self.view_results_button.setEnabled(self.last_results is not None)
        self.export_excel_button.setEnabled(successful > 0 and self.last_results is not None)
        self.show_errors_button.setEnabled(failed > 0)

    def update_statistics_display(self, stats: Dict[str, int]) -> None:
        self.students_count_label.setText(str(stats.get("students", 0)))
        self.mentors_count_label.setText(str(stats.get("mentors", 0)))
        self.total_capacity_label.setText(str(stats.get("total_capacity", 0)))
        self.available_capacity_label.setText(str(stats.get("available_capacity", 0)))

    def _handle_allocation_completed(self, results: Dict[str, object]) -> None:
        # slot primarily for observers; current page already handles results directly
        _ = results

    # ------------------------------------------------------------------
    # Actions - details & export
    # ------------------------------------------------------------------
    def show_detailed_results(self) -> None:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ نمایش جزئیات نتایج انجام نشد.")
            return
        if not self.last_results:
            QMessageBox.information(self, "", "    ")
            return

        assignments = self.last_results.get("assignments", [])
        errors = self.last_results.get("errors", [])
        message = [
            f" : {len(assignments)}",
            f" : {len(errors)}",
        ]
        QMessageBox.information(self, " ", "\n".join(message))

    def show_allocation_errors(self) -> None:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ نمایش خطاهای تخصیص انجام نشد.")
            return
        if not self.last_results or not self.last_results.get("errors"):
            QMessageBox.information(self, "", "   ")
            return
        errors = self.last_results.get("errors", [])
        details = "\n".join(
            f"?? ԝ {err.get('student_id')} ? {err.get('reason')}" for err in errors
        )
        QMessageBox.information(self, " ", details)

    def _on_start_clicked(self) -> None:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ رویداد شروع تخصیص نادیده گرفته شد.")
            return
        self.run_async(self.start_allocation())

    def _on_export_clicked(self) -> None:
        if getattr(self, "_minimal_mode", False):
            self.LOGGER.info("حالت UI مینیمال فعال است؛ فرآیند خروجی اکسل اجرا نشد.")
            return
        if not self.last_results:
            QMessageBox.information(self, "", "    ")
            return

        default_path = str(Path.home() / "allocation_results.xlsx")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "  ",
            default_path,
            "Excel Files (*.xlsx)",
        )
        if not file_path:
            return

        task = self.presenter.export_results(self.last_results, file_path)
        if isinstance(task, Awaitable):
            self.run_async(task)
            QMessageBox.information(self, "", "   ")
        else:
            QMessageBox.information(self, "", "     ")

    def _handle_backend_error(self, message: str) -> None:
        QMessageBox.warning(self, " ", message)
