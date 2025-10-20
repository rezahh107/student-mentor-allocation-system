from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable


def run_coro_safe(coro_factory: Callable[[], Awaitable[Any]]) -> None:
    """اجرای امن یک coroutine در پس‌زمینه.

    اگر event loop در دسترس باشد، از create_task استفاده می‌شود؛ در غیر این صورت
    از asyncio.run استفاده می‌گردد (برای محیط‌های تست).
    """

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro_factory())
    except RuntimeError:
        asyncio.run(coro_factory())

