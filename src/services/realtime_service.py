from __future__ import annotations

import asyncio
import json
from typing import Optional
import contextlib

from PyQt5.QtCore import QObject, pyqtSignal


class RealtimeService(QObject):
    """سرویس دریافت به‌روزرسانی‌های بلادرنگ از WebSocket (اختیاری)."""

    data_updated = pyqtSignal(dict)

    def __init__(self, websocket_url: str = "ws://localhost:8000/ws") -> None:
        super().__init__()
        self.websocket_url = websocket_url
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """شروع شنود. نیازمند نصب بسته websockets است."""
        try:
            import websockets  # type: ignore
        except Exception:  # noqa: BLE001
            return

        self._running = True

        async def _runner() -> None:
            try:
                async with websockets.connect(self.websocket_url) as ws:  # type: ignore[attr-defined]
                    while self._running:
                        msg = await ws.recv()
                        try:
                            data = json.loads(msg)
                            if isinstance(data, dict):
                                self.data_updated.emit(data)
                        except json.JSONDecodeError:
                            continue
            except Exception:
                # silent retry/backoff could be added
                await asyncio.sleep(2)
                if self._running:
                    await _runner()

        self._task = asyncio.create_task(_runner())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(Exception):
                await self._task
            self._task = None

    # Alias for compatibility with suggested API
    async def start_listening(self) -> None:
        await self.start()
