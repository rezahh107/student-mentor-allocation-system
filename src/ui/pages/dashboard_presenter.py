from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
import qasync

from src.api.client import APIClient
from src.core.clock import SupportsNow, tehran_clock
from src.services.analytics_service import AnalyticsService, DashboardData
from src.services.realtime_service import RealtimeService
from src.services.report_service import DashboardReportGenerator


class DashboardPresenter(QObject):
    """پرزنتر داشبورد با بارگذاری داده‌ها، کش و بروزرسانی خودکار."""

    data_loaded = pyqtSignal(object)  # DashboardData
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, api_client: Optional[APIClient] = None, *, clock: SupportsNow | None = None) -> None:
        super().__init__()
        self.api_client = api_client or APIClient(use_mock=True)
        self.clock = clock or tehran_clock()
        self.analytics_service = AnalyticsService(self.api_client, clock=self.clock)
        self.report_generator = DashboardReportGenerator(clock=self.clock)

        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(lambda: qasync.asyncSlot()(self.refresh_data)())
        self.refresh_interval = 300000  # 5m
        self._current_data: Optional[DashboardData] = None
        self._current_range: Optional[Tuple[datetime, datetime]] = None
        # Realtime
        self.realtime_service: Optional[RealtimeService] = None
        self.realtime_enabled: bool = False

    @qasync.asyncSlot()
    async def load_dashboard_data(self, date_range: Optional[Tuple[datetime, datetime]] = None, force_refresh: bool = False):
        try:
            self.loading_started.emit()
            # validate range
            if date_range and date_range[0] > date_range[1]:
                raise ValueError("تاریخ شروع نمی‌تواند بعد از تاریخ پایان باشد")
            data = await asyncio.wait_for(
                self.analytics_service.load_dashboard_data(date_range, force_refresh=force_refresh),
                timeout=30.0,
            )
            if not data:
                raise ValueError("داده‌ای دریافت نشد")
            self._current_data = data
            self._current_range = date_range
            self.data_loaded.emit(data)
        except asyncio.TimeoutError:
            self.error_occurred.emit("زمان بارگذاری داده‌ها به پایان رسید. لطفاً دوباره تلاش کنید.")
        except ValueError as e:  # noqa: BLE001
            self.error_occurred.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.error_occurred.emit(f"خطا در بارگذاری داده‌ها: {e}")
        finally:
            self.loading_finished.emit()

    @qasync.asyncSlot()
    async def refresh_data(self):
        await self.load_dashboard_data(self._current_range, force_refresh=True)

    def start_auto_refresh(self, interval_ms: int = 300000) -> None:
        self.refresh_interval = interval_ms
        self.auto_refresh_timer.start(interval_ms)

    def stop_auto_refresh(self) -> None:
        self.auto_refresh_timer.stop()

    @qasync.asyncSlot()
    async def export_pdf_report(self, filepath: str):
        if not self._current_data:
            raise RuntimeError("داده‌ای برای گزارش موجود نیست")
        await self.report_generator.generate_dashboard_pdf(self._current_data, filepath)

    def enable_realtime_updates(self, websocket_url: str = "ws://localhost:8000/ws") -> None:
        """فعال‌سازی به‌روزرسانی بلادرنگ داشبورد."""
        if not self.realtime_service:
            self.realtime_service = RealtimeService(websocket_url)
            self.realtime_service.data_updated.connect(self._handle_realtime_update)
        if not self.realtime_enabled:
            # fire-and-forget
            import asyncio as _aio
            _aio.create_task(self.realtime_service.start_listening())
            self.realtime_enabled = True

    def _handle_realtime_update(self, data: dict) -> None:
        if isinstance(data, dict) and data.get("type") == "student_update":
            import asyncio as _aio
            _aio.create_task(self.load_dashboard_data(force_refresh=True))
