from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List


Callback = Callable[[Any], Any]


class EventBus:
    """اتوبوس رویداد ساده برای ارتباط مؤلفه‌ها.

    متدها:
        subscribe: ثبت تابع شنونده برای یک رویداد.
        emit: انتشار رویداد برای همه شنونده‌ها (پشتیبانی از async).
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callback]] = {}

    def subscribe(self, event: str, callback: Callback) -> None:
        """ثبت شنونده برای رویداد مشخص."""
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(callback)

    async def emit(self, event: str, data: Any = None) -> None:
        """انتشار رویداد به همه شنونده‌ها (sync/async)."""
        callbacks = list(self._subscribers.get(event, []))
        for cb in callbacks:
            if asyncio.iscoroutinefunction(cb):
                await cb(data)
            else:
                cb(data)

