from __future__ import annotations

import asyncio
import logging
from typing import Literal

from src.api.client import APIClient
from src.core.clock import tehran_clock
from src.ui.core.app_state import AppState
from src.ui.core.event_bus import EventBus


class MainPresenter:
    """پرزنتر پنجره اصلی بر اساس الگوی MVP.

    وظایف:
        - هماهنگی منطق تجاری و فراخوانی‌های API
        - مدیریت State مرکزی و انتشار رویدادها
    """

    def __init__(self, api_client: APIClient) -> None:
        self.api_client = api_client
        self.state = AppState(api_mode=("mock" if api_client.use_mock else "real"))
        self.event_bus = EventBus()
        self.clock = tehran_clock()

    async def initialize(self) -> None:
        """بارگذاری اولیه برنامه و بررسی سلامت API."""
        try:
            is_healthy = await self.api_client.health_check()
            if not is_healthy and not self.api_client.use_mock:
                self.api_client.use_mock = True
                self.state.api_mode = "mock"
                await self.event_bus.emit("api_mode_changed", "mock")
            await self.refresh_all_data()
        except Exception as e:  # noqa: BLE001
            await self.event_bus.emit("error", e)

    async def refresh_all_data(self) -> None:
        """بروزرسانی موازی داده‌ها از API."""
        await self.event_bus.emit("loading_start", "در حال دریافت اطلاعات...")
        try:
            results = await asyncio.gather(
                self.api_client.get_students(),
                self.api_client.get_mentors(),
                self.api_client.get_dashboard_stats(),
                return_exceptions=True,
            )

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logging.error("Error fetching data %s: %s", i, result)
                else:
                    if i == 0:
                        self.state.students = result
                    elif i == 1:
                        self.state.mentors = result
                    elif i == 2:
                        self.state.stats = result

            self.state.last_update = self.clock.now()
            await self.event_bus.emit("data_updated", self.state)
        finally:
            await self.event_bus.emit("loading_end")

    async def fetch_students(self) -> list:
        """دریافت دانش‌آموزان (برای اکشن‌های مستقل)."""
        return await self.api_client.get_students()

    async def fetch_mentors(self) -> list:
        """دریافت منتورها (برای اکشن‌های مستقل)."""
        return await self.api_client.get_mentors()

    async def fetch_stats(self):  # type: ignore[override]
        """دریافت آمار داشبورد (برای اکشن‌های مستقل)."""
        return await self.api_client.get_dashboard_stats()

    async def switch_api_mode(self, mode: Literal["mock", "real"]) -> None:
        """تغییر حالت API بین mock/real و بروزرسانی داده‌ها."""
        self.api_client.use_mock = mode == "mock"
        self.state.api_mode = mode
        await self.event_bus.emit("api_mode_changed", mode)
        await self.refresh_all_data()

