"""Common helpers for UI pages."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Optional

from PySide6.QtWidgets import QWidget


class BasePage(QWidget):
    """Base widget that offers small Qt-aware async helpers."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._background_tasks: list[asyncio.Task] = []

    def run_async(self, coro: Awaitable) -> Optional[asyncio.Task]:
        """Schedule an awaitable on the active event loop.

        Falls back to ``asyncio.run`` when no loop is running (e.g. unit tests).
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return None

        task = loop.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(lambda t: self._background_tasks.remove(t) if t in self._background_tasks else None)
        return task

    def closeEvent(self, event):  # noqa: D401, ANN001
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        self._background_tasks.clear()
        super().closeEvent(event)
