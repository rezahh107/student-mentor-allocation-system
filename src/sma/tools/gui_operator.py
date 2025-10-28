"""Headless-friendly Operator GUI shim for CI environments."""
from __future__ import annotations

import collections
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

try:  # pragma: no cover - native path only hit locally
    from sma._local_tools.gui_operator import HEADLESS_DIAGNOSTIC as _BASE_DIAGNOSTIC
except Exception:  # pragma: no cover - fallback for trimmed deps
    _BASE_DIAGNOSTIC = (
        "GUI_HEADLESS_SKIPPED: اجرای رابط گرافیکی در محیط بدون نمایشگر پشتیبانی نمی‌شود."
    )

HEADLESS_DIAGNOSTIC = _BASE_DIAGNOSTIC


@dataclass(slots=True)
class _StringVar:
    value: str = ""

    def set(self, new_value: str) -> None:
        self.value = new_value

    def get(self) -> str:
        return self.value


@dataclass(slots=True)
class _ListStub:
    items: list[str] = field(default_factory=list)

    def delete(self, _start: int, _end: Optional[int] = None) -> None:
        self.items.clear()

    def insert(self, _index: int, value: str) -> None:
        self.items.append(value)


@dataclass(slots=True)
class _HeadlessRoot:
    """Minimal stub mimicking Tk ``Tk`` interface used in tests."""

    destroyed: bool = False
    scheduled: list[tuple[int, Callable[[], None]]] = field(default_factory=list)

    def withdraw(self) -> None:  # pragma: no cover - noop for API parity
        return None

    def destroy(self) -> None:
        self.destroyed = True

    def after(self, _delay: int, callback: Callable[[], None]) -> None:
        # execute immediately to preserve determinism during tests
        self.scheduled.append((_delay, callback))
        callback()

    def deiconify(self) -> None:  # pragma: no cover - noop for API parity
        return None

    def mainloop(self) -> None:  # pragma: no cover - never invoked in CI
        raise RuntimeError(HEADLESS_DIAGNOSTIC)

    def protocol(self, *_args: object, **_kwargs: object) -> None:  # pragma: no cover - noop
        return None


@dataclass(slots=True)
class _StubDispatcher:
    """Thread-safe dispatcher used by the headless GUI stub."""

    def dispatch_once(self) -> int:
        return 0


@dataclass(slots=True)
class HeadlessPublisher:
    """Minimal publisher replicating the public API used by tests."""

    sink: "OperatorGUI"

    def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
        message = (
            f"رویداد {event_type} با کلید {headers.get('x-idempotency-key', '---')} منتشر شد"
        )
        self.sink.enqueue_log(message)


class OperatorGUI:
    """Thread-safe queue bridge without GUI dependencies."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        dispatcher_factory: Callable[[HeadlessPublisher], tuple[_StubDispatcher, Callable[[], None]]]
        | None = None,
    ) -> None:
        self.root = _HeadlessRoot()
        self.database_var = _StringVar(database_url or "sqlite:///allocation.db")
        self.status_var = _StringVar("آماده")
        self.metrics_var = _StringVar("PENDING=0 | SENT=0 | FAILED=0")
        self.banner_var = _StringVar("")
        self.status_list = _ListStub()

        self._queue: "queue.Queue[tuple[str, tuple]]" = queue.Queue()
        self._status_lines: "collections.deque[str]" = collections.deque(maxlen=20)
        self._logs: list[str] = []
        self._metrics: dict[str, int] = {"PENDING": 0, "SENT": 0, "FAILED": 0}
        self._stop_event = threading.Event()
        self._dispatcher_thread: threading.Thread | None = None
        self._dispatcher_running = False
        self._publisher = HeadlessPublisher(sink=self)
        self._dispatcher_factory = dispatcher_factory or self._default_dispatcher_factory

        # keep behaviour compatible with Tk variant by processing queue eagerly
        self.root.after(200, self._process_pending)

    # ------------------------------------------------------------------
    # Queue bridge
    # ------------------------------------------------------------------
    def enqueue_log(self, message: str) -> None:
        self._queue.put(("log", (message,)))

    def enqueue_status(self, event_id: str, status: str, extra: dict[str, object]) -> None:
        self._queue.put(("status", (event_id, status, extra)))

    def _set_banner(self, message: str) -> None:
        self._queue.put(("banner", (message,)))

    def _process_pending(self) -> None:
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                (message,) = payload
                self._logs.append(message)
            elif kind == "status":
                event_id, status, extra = payload
                self._update_status(event_id, status, extra)
            elif kind == "banner":
                (message,) = payload
                self.banner_var.set(message)

    def _drain_queue_for_test(self) -> None:
        self._process_pending()

    # ------------------------------------------------------------------
    # Dispatcher controls
    # ------------------------------------------------------------------
    def _default_dispatcher_factory(
        self, publisher: HeadlessPublisher
    ) -> tuple[_StubDispatcher, Callable[[], None]]:
        return _StubDispatcher(), lambda: None

    def _run_dispatcher(self) -> None:
        dispatcher: _StubDispatcher | None = None
        cleanup: Optional[Callable[[], None]] = None
        try:
            dispatcher, cleanup = self._dispatcher_factory(self._publisher)
            while not self._stop_event.is_set():
                sent = dispatcher.dispatch_once()
                if sent == 0:
                    self._stop_event.wait(0.05)
        except Exception as exc:  # pragma: no cover - defensive guard
            self.enqueue_log(f"اجرای دیسپچر با خطا متوقف شد: {exc}")
            self.status_var.set("خطای دیسپچر")
        finally:
            if cleanup:
                try:
                    cleanup()
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    self.enqueue_log(f"پاک‌سازی دیسپچر با خطا مواجه شد: {exc}")
            self._dispatcher_running = False
            self._dispatcher_thread = None
            self._stop_event.clear()
            self.enqueue_log("دیسپچر متوقف شد")
            self.status_var.set("آماده")
            self._set_banner("دیسپچر متوقف شد")
            self._drain_queue_for_test()

    def _start_dispatcher(self) -> None:
        if self._dispatcher_running and self._dispatcher_thread and self._dispatcher_thread.is_alive():
            warning = "هشدار: فرایند در حال اجراست"
            self._set_banner(warning)
            self.enqueue_log(warning)
            return
        self._stop_event.clear()
        self._dispatcher_running = True
        self._dispatcher_thread = threading.Thread(target=self._run_dispatcher, daemon=True)
        self._dispatcher_thread.start()
        self.status_var.set("دیسپچر فعال شد")
        self.enqueue_log("دیسپچر در حال اجراست")
        self._set_banner("دیسپچر فعال شد")
        self._drain_queue_for_test()

    def _stop_dispatcher(self) -> None:
        if not self._dispatcher_running or not self._dispatcher_thread:
            warning = "هشدار: دیسپچر غیرفعال است"
            self._set_banner(warning)
            self.enqueue_log(warning)
            self._drain_queue_for_test()
            return
        self._stop_event.set()
        self._dispatcher_thread.join(timeout=1.0)
        self._drain_queue_for_test()

    def _refresh_status(self) -> None:
        self.enqueue_log("پیکربندی به‌روزرسانی شد؛ در صورت نیاز دیسپچر را مجدداً راه‌اندازی کنید")
        self._drain_queue_for_test()

    def _update_status(self, event_id: str, status: str, extra: dict[str, object]) -> None:
        self._metrics.setdefault(status, 0)
        self._metrics[status] += 1
        metrics_repr = " | ".join(f"{key}={value}" for key, value in self._metrics.items())
        self.metrics_var.set(metrics_repr)
        description = f"{status} ← {event_id} ({extra})"
        self._status_lines.appendleft(description)
        self.status_var.set(f"آخرین وضعیت: {status}")
        self.status_list.delete(0, None)
        for item in self._status_lines:
            self.status_list.insert(len(self.status_list.items), item)

    # ------------------------------------------------------------------
    def run(self) -> None:  # pragma: no cover - GUI loop not exercised in CI
        raise RuntimeError(HEADLESS_DIAGNOSTIC)
