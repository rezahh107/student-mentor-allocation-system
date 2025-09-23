from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from PyQt5.QtWidgets import QPushButton


class AsyncButton(QPushButton):
    """دکمه آگاه از async که هنگام اجرا خود را غیرفعال می‌کند.

    ویژگی‌ها:
        set_async_handler: ثبت تابع coroutine برای رویداد کلیک.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._handler: Optional[Callable[[], Awaitable[None]]] = None
        self.clicked.connect(self._on_clicked)

    def set_async_handler(self, handler: Callable[[], Awaitable[None]]) -> None:
        self._handler = handler

    def _on_clicked(self) -> None:
        if not self._handler:
            return
        self.setEnabled(False)

        async def _wrap() -> None:
            try:
                await self._handler()
            finally:
                self.setEnabled(True)

        asyncio.create_task(_wrap())

