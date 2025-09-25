"""پنل مینیمال Tkinter برای دیسپچر اوتباکس با صف thread-safe."""
from __future__ import annotations

import collections
import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional

try:  # pragma: no cover - در تست‌ها ممکن است Tk در دسترس نباشد
    import tkinter as tk
    from tkinter import ttk
except Exception as exc:  # pragma: no cover - در محیط headless
    tk = None  # type: ignore[assignment]
    _TK_IMPORT_ERROR = exc
else:
    _TK_IMPORT_ERROR = None

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.phase3_allocation.outbox import OutboxDispatcher, Publisher, SystemClock

HEADLESS_DIAGNOSTIC = (
    "GUI_HEADLESS_SKIPPED: اجرای رابط گرافیکی در محیط بدون نمایشگر پشتیبانی نمی‌شود."
)


@dataclass(slots=True)
class TkPublisher(Publisher):
    """انتشار رویداد به صف رابط گرافیکی."""

    sink: "OperatorGUI"

    def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
        message = (
            f"رویداد {event_type} با کلید {headers.get('x-idempotency-key', '---')} منتشر شد"
        )
        self.sink.enqueue_log(message)


class OperatorGUI:
    """پنل حداقلی با صف thread-safe و دیسپچر طولانی‌مدت."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        dispatcher_factory: Callable[[TkPublisher], tuple[OutboxDispatcher, Callable[[], None]]]
        | None = None,
    ) -> None:
        if tk is None:
            raise RuntimeError(f"{HEADLESS_DIAGNOSTIC} (ImportError: {_TK_IMPORT_ERROR})")
        self.root = self._create_root()
        self.root.withdraw()

        self.database_var = tk.StringVar(
            value=database_url or os.environ.get("DATABASE_URL", "sqlite:///allocation.db")
        )
        self.status_var = tk.StringVar(value="آماده")
        self.metrics_var = tk.StringVar(value="PENDING=0 | SENT=0 | FAILED=0")
        self.banner_var = tk.StringVar(value="")

        self._queue: "queue.Queue[tuple[str, tuple]]" = queue.Queue()
        self._status_lines: "collections.deque[str]" = collections.deque(maxlen=20)
        self._metrics = {"PENDING": 0, "SENT": 0, "FAILED": 0}
        self._stop_event = threading.Event()
        self._dispatcher_thread: threading.Thread | None = None
        self._publisher = TkPublisher(sink=self)
        self._clock = SystemClock()
        self._dispatcher_factory = dispatcher_factory or self._default_dispatcher_factory

        self._build_layout()
        self.root.after(200, self._process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _create_root(self) -> "tk.Tk":
        if tk is None:
            raise RuntimeError(HEADLESS_DIAGNOSTIC)
        try:
            root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover - در محیط headless
            raise RuntimeError(f"{HEADLESS_DIAGNOSTIC}: {exc}") from exc
        root.title("پنل مینیمال دیسپچر")
        root.geometry("720x520")
        return root

    def _build_layout(self) -> None:
        if tk is None:
            raise RuntimeError(HEADLESS_DIAGNOSTIC)
        padding = {"padx": 8, "pady": 4}

        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.X, **padding)

        ttk.Label(frame, text="آدرس پایگاه‌داده:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(frame, textvariable=self.database_var, width=50).grid(row=0, column=1, sticky=tk.W)
        ttk.Button(frame, text="به‌روزرسانی", command=self._refresh_status).grid(row=0, column=2, padx=4)

        control = ttk.LabelFrame(self.root, text="کنترل دیسپچر")
        control.pack(fill=tk.X, **padding)
        ttk.Button(control, text="شروع", command=self._start_dispatcher).grid(row=0, column=0, padx=4)
        ttk.Button(control, text="توقف", command=self._stop_dispatcher).grid(row=0, column=1, padx=4)
        ttk.Label(control, textvariable=self.metrics_var).grid(row=0, column=2, sticky=tk.W)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, **padding)
        ttk.Label(status_frame, text="وضعیت جاری:").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

        history = ttk.LabelFrame(self.root, text="آخرین وضعیت‌ها")
        history.pack(fill=tk.BOTH, expand=True, **padding)
        self.status_list = tk.Listbox(history, height=8)
        self.status_list.pack(fill=tk.BOTH, expand=True)

        banner = ttk.Frame(self.root)
        banner.pack(fill=tk.X, **padding)
        ttk.Label(banner, textvariable=self.banner_var).pack(side=tk.LEFT)

        logs = ttk.LabelFrame(self.root, text="گزارش رویداد")
        logs.pack(fill=tk.BOTH, expand=True, **padding)
        self.log_text = tk.Text(logs, height=8, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Queue bridge
    # ------------------------------------------------------------------
    def enqueue_log(self, message: str) -> None:
        self._queue.put(("log", (message,)))

    def enqueue_status(self, event_id: str, status: str, extra: dict[str, object]) -> None:
        self._queue.put(("status", (event_id, status, extra)))

    def _process_pending(self) -> None:
        if tk is None:
            raise RuntimeError(HEADLESS_DIAGNOSTIC)
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                (message,) = payload
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
            elif kind == "status":
                event_id, status, extra = payload
                self._update_status(event_id, status, extra)
            elif kind == "banner":
                (message,) = payload
                self.banner_var.set(message)

    def _process_queue(self) -> None:
        if tk is None:
            raise RuntimeError(HEADLESS_DIAGNOSTIC)
        self._process_pending()
        self.root.after(200, self._process_queue)

    def _drain_queue_for_test(self) -> None:
        """فرآوری صف بدون زمان‌بندی مجدد برای تست‌ها."""

        if tk is None:
            return
        self._process_pending()

    def _set_banner(self, message: str) -> None:
        self._queue.put(("banner", (message,)))

    def _update_status(self, event_id: str, status: str, extra: dict[str, object]) -> None:
        self._metrics.setdefault(status, 0)
        self._metrics[status] += 1
        self.metrics_var.set(" | ".join(f"{k}={v}" for k, v in self._metrics.items()))
        description = f"{status} ← {event_id} ({extra})"
        self._status_lines.appendleft(description)
        self.status_list.delete(0, tk.END)
        for line in self._status_lines:
            self.status_list.insert(tk.END, line)
        self.status_var.set(f"آخرین وضعیت: {status}")

    # ------------------------------------------------------------------
    # Dispatcher control
    # ------------------------------------------------------------------
    def _default_dispatcher_factory(
        self, publisher: TkPublisher
    ) -> tuple[OutboxDispatcher, Callable[[], None]]:
        engine = create_engine(self.database_var.get(), future=True)
        SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        session = SessionFactory()
        dispatcher = OutboxDispatcher(
            session=session,
            publisher=publisher,
            clock=self._clock,
            status_hook=lambda event_id, status, extra: self.enqueue_status(event_id, status, extra),
        )

        def cleanup() -> None:
            session.close()
            engine.dispose()

        return dispatcher, cleanup

    def _start_dispatcher(self) -> None:
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            warning = "هشدار: فرایند در حال اجراست"
            self._set_banner(warning)
            self.enqueue_log(warning)
            return
        self._stop_event.clear()
        self._dispatcher_thread = threading.Thread(target=self._run_dispatcher, daemon=True)
        self._dispatcher_thread.start()
        self.status_var.set("دیسپچر فعال شد")
        self.enqueue_log("دیسپچر در حال اجراست")
        self._set_banner("دیسپچر فعال شد")

    def _run_dispatcher(self) -> None:
        dispatcher: Optional[OutboxDispatcher] = None
        cleanup: Optional[Callable[[], None]] = None
        try:
            dispatcher, cleanup = self._dispatcher_factory(self._publisher)
            while not self._stop_event.is_set():
                sent = dispatcher.dispatch_once()
                if sent == 0:
                    self._stop_event.wait(1.0)
        except Exception as exc:  # pragma: no cover - نگهبان GUI
            self.enqueue_log(f"اجرای دیسپچر با خطا متوقف شد: {exc}")
            self.status_var.set("خطای دیسپچر")
        finally:
            if cleanup:
                cleanup()
            self._stop_event.clear()
            self.enqueue_log("دیسپچر متوقف شد")
            self.status_var.set("آماده")
            self._set_banner("دیسپچر متوقف شد")

    def _stop_dispatcher(self) -> None:
        if not self._dispatcher_thread or not self._dispatcher_thread.is_alive():
            warning = "هشدار: دیسپچر غیرفعال است"
            self._set_banner(warning)
            self.enqueue_log(warning)
            return
        self._stop_event.set()
        self._dispatcher_thread.join(timeout=5)
        self._dispatcher_thread = None

    def _refresh_status(self) -> None:
        self.enqueue_log("پیکربندی به‌روزرسانی شد؛ در صورت نیاز دیسپچر را مجدداً راه‌اندازی کنید")

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.root.deiconify()
        self.root.mainloop()

    def _on_close(self) -> None:
        self._stop_event.set()
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            self._dispatcher_thread.join(timeout=2)
        self.root.destroy()


def main() -> None:
    gui = OperatorGUI()
    gui.run()


if __name__ == "__main__":  # pragma: no cover - اجرا به صورت مستقیم
    main()
