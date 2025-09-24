"""Optional Tkinter harness for monitoring counter backfills."""
from __future__ import annotations

import json
import logging
import os
import queue
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, MutableMapping, Optional, Sequence, Tuple

from src.phase2_counter_service.types import BackfillObserver

try:  # pragma: no cover - optional dependency resolution
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - Tk not available
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]


EventPayload = Dict[str, Any]
EventTuple = Tuple[str, EventPayload]


class QueueBackfillObserver(BackfillObserver):
    """Adapter that forwards observer hooks into a queue for GUI consumption."""

    def __init__(self, sink: "EventSink") -> None:
        self._sink = sink

    def on_chunk(self, chunk_index: int, applied: int, reused: int, skipped: int) -> None:
        payload = {
            "chunk": chunk_index,
            "applied": applied,
            "reused": reused,
            "skipped": skipped,
        }
        self._sink.emit(("progress", payload))

    # Optional hooks used by the GUI; the core pipeline ignores them when absent.
    def on_warning(self, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        payload: EventPayload = {"message": message, "details": dict(details or {})}
        self._sink.emit(("warning", payload))

    def on_conflict(self, conflict_type: str, details: Optional[Mapping[str, Any]] = None) -> None:
        payload: EventPayload = {"kind": conflict_type, "details": dict(details or {})}
        self._sink.emit(("conflict", payload))


class HeadlessObserver(BackfillObserver):
    """No-op observer used when the application runs without a display."""

    def on_chunk(self, chunk_index: int, applied: int, reused: int, skipped: int) -> None:
        return None

    def on_warning(self, message: str, details: Optional[Mapping[str, Any]] = None) -> None:
        return None

    def on_conflict(self, conflict_type: str, details: Optional[Mapping[str, Any]] = None) -> None:
        return None


class EventSink:
    """Thread-safe queue bridge used by :class:`OperatorPanel`."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[EventTuple]" = queue.Queue()

    def emit(self, event: EventTuple) -> None:
        self._queue.put(event)

    def drain(self) -> Sequence[EventTuple]:
        events: list[EventTuple] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events


class ObserverLogHandler(logging.Handler):
    """Parse structured log records and forward warnings/conflicts to the GUI."""

    def __init__(self, observer: QueueBackfillObserver) -> None:
        super().__init__(level=logging.WARNING)
        self._observer = observer
        self.is_operator_panel_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload: MutableMapping[str, Any] = json.loads(record.getMessage())
        except json.JSONDecodeError:
            payload = {"پیام": record.getMessage()}
        message = str(payload.get("پیام", "هشدار"))
        if message == "conflict_resolved":
            conflict = str(payload.get("نوع", "unknown"))
            self._observer.on_conflict(conflict, payload)
        else:
            self._observer.on_warning(message, payload)


@dataclass(slots=True)
class OperatorPanel:
    """Tkinter dashboard presenting progress and warnings in Persian."""

    root: "tk.Tk"
    sink: EventSink = field(default_factory=EventSink)
    logger: Optional[logging.Logger] = None
    _observer: QueueBackfillObserver = field(init=False, repr=False)
    _logger: logging.Logger = field(init=False, repr=False)
    _log_handler: ObserverLogHandler = field(init=False, repr=False)
    _handler_attached: bool = field(init=False, repr=False, default=False)
    _running: bool = field(init=False, repr=False, default=False)
    _applied_total: int = field(init=False, repr=False, default=0)
    _reused_total: int = field(init=False, repr=False, default=0)
    _skipped_total: int = field(init=False, repr=False, default=0)
    _progress_var: Any = field(init=False, repr=False)
    _progress: Any = field(init=False, repr=False)
    _status_var: Any = field(init=False, repr=False)
    _warnings: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._observer = QueueBackfillObserver(self.sink)
        self._logger = self.logger or logging.getLogger("counter-service")
        self._log_handler = ObserverLogHandler(self._observer)
        self._handler_attached = False
        self._attach_handler()
        self._build_ui()
        self._running = True
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.root.after(200, self._process_events)
        self._applied_total = 0
        self._reused_total = 0
        self._skipped_total = 0

    def _attach_handler(self) -> None:
        for handler in list(self._logger.handlers):
            if getattr(handler, "is_operator_panel_handler", False):
                self._logger.removeHandler(handler)
                handler.close()
        self._logger.addHandler(self._log_handler)
        self._handler_attached = True

    def _build_ui(self) -> None:
        self.root.title("پنل پایش سرویس شمارنده")
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="پیشرفت بک‌فیل", anchor="w").pack(fill=tk.X)
        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress = ttk.Progressbar(frame, variable=self._progress_var, maximum=100)
        self._progress.pack(fill=tk.X, pady=(4, 8))

        self._status_var = tk.StringVar(value="در انتظار شروع")
        ttk.Label(frame, textvariable=self._status_var, anchor="w").pack(fill=tk.X)

        ttk.Label(frame, text="هشدارها", anchor="w").pack(fill=tk.X, pady=(12, 4))
        self._warnings = tk.Listbox(frame, height=6)
        self._warnings.pack(fill=tk.BOTH, expand=True)

    @property
    def observer(self) -> QueueBackfillObserver:
        return self._observer

    def _process_events(self) -> None:
        for event, payload in self.sink.drain():
            if event == "progress":
                self._handle_progress(payload)
            elif event == "warning":
                self._handle_warning(payload)
            elif event == "conflict":
                self._handle_conflict(payload)
        if self._running:
            self.root.after(200, self._process_events)

    def _handle_progress(self, payload: Mapping[str, Any]) -> None:
        applied = int(payload.get("applied", 0))
        reused = int(payload.get("reused", 0))
        skipped = int(payload.get("skipped", 0))
        chunk = int(payload.get("chunk", 0))
        total = applied + reused + skipped
        self._applied_total += applied
        self._reused_total += reused
        self._skipped_total += skipped
        percentage = (applied + reused) / total * 100 if total else 0.0
        self._progress_var.set(min(100.0, percentage))
        status = (
            f"دسته {chunk}: اعمال {applied} (جمع {self._applied_total})، "
            f"استفاده مجدد {reused} (جمع {self._reused_total})، "
            f"خشک {skipped} (جمع {self._skipped_total})"
        )
        self._status_var.set(status)

    def _handle_warning(self, payload: Mapping[str, Any]) -> None:
        message = str(payload.get("message", "هشدار"))
        self._warnings.insert(tk.END, message)
        self._warnings.see(tk.END)

    def _handle_conflict(self, payload: Mapping[str, Any]) -> None:
        kind = str(payload.get("kind", "unknown"))
        message = f"تعارض برطرف شد: {kind}"
        self._warnings.insert(tk.END, message)
        self._warnings.see(tk.END)

    def shutdown(self) -> None:
        if not self._running:
            return
        self._running = False
        self._detach_handler()
        try:
            self.root.quit()
        except Exception:  # pragma: no cover - Tk teardown edge
            pass
        try:
            self.root.destroy()
        except Exception:  # pragma: no cover - Tk teardown edge
            pass

    def _detach_handler(self) -> None:
        if self._handler_attached:
            self._logger.removeHandler(self._log_handler)
            self._handler_attached = False
        self._log_handler.close()

    def run(self) -> None:
        self.root.mainloop()


def _is_display_available() -> bool:
    if tk is None:
        return False
    if sys.platform.startswith("win"):
        return True
    for env in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"):
        if os.environ.get(env):
            return True
    return False


def build_headless_observer() -> HeadlessObserver:
    """Return a no-op observer for headless smoke tests."""

    return HeadlessObserver()


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv
    if not _is_display_available():
        print("محیط بدون نمایشگر؛ پنل گرافیکی در دسترس نیست.")
        return 0
    if tk is None:
        print("کتابخانه Tkinter یافت نشد؛ حالت CLI ادامه دارد.")
        return 0
    try:
        root = tk.Tk()
    except tk.TclError:
        print("محیط بدون نمایشگر؛ پنل گرافیکی در دسترس نیست.")
        return 0
    panel = OperatorPanel(root)
    try:
        panel.run()
    finally:
        panel.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover - manual execution
    sys.exit(main())
