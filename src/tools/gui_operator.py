"""Tkinter operator panel for allocation and dispatcher control."""
from __future__ import annotations

import csv
import json
import logging
import os
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.phase3_allocation.allocation_tx import AllocationRequest, AllocationResult
from src.phase3_allocation.outbox import OutboxDispatcher, Publisher, SystemClock
from src.tools.allocation_cli import build_allocator

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TkPublisher(Publisher):
    """Publisher that forwards events to the GUI log."""

    sink: "OperatorGUI"

    def publish(self, *, event_type: str, payload: dict, headers: dict[str, str]) -> None:
        message = f"رویداد {event_type} برای تخصیص {payload.get('allocation_id')} منتشر شد"
        self.sink.enqueue_log(message)


class OperatorGUI:
    """Minimal Tkinter panel for allocation operators."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("پنل عملیاتی تخصیص")
        self.root.geometry("840x600")

        self.database_var = tk.StringVar(value=os.environ.get("DATABASE_URL", "sqlite:///allocation.db"))
        self.file_var = tk.StringVar()
        self.status_var = tk.StringVar(value="آماده")
        self.metrics_var = tk.StringVar(value="PENDING=0 | SENT=0 | FAILED=0")

        self.event_queue: "queue.Queue[tuple[str, tuple]]" = queue.Queue()
        self._dispatcher_thread: threading.Thread | None = None
        self._dispatcher_stop = threading.Event()
        self._metrics = {"PENDING": 0, "SENT": 0, "FAILED": 0}
        self._recent_events: list[str] = []
        self._max_events = 20

        self._build_layout()
        self.root.after(200, self._process_queue)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        padding = {"padx": 8, "pady": 4}

        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill=tk.X, **padding)

        ttk.Label(top_frame, text="آدرس پایگاه‌داده:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(top_frame, textvariable=self.database_var, width=60).grid(row=0, column=1, sticky=tk.W)

        ttk.Label(top_frame, text="فایل درخواست‌ها:").grid(row=1, column=0, sticky=tk.W)
        entry = ttk.Entry(top_frame, textvariable=self.file_var, width=60)
        entry.grid(row=1, column=1, sticky=tk.W)
        ttk.Button(top_frame, text="انتخاب فایل", command=self._browse_file).grid(row=1, column=2, sticky=tk.W, padx=4)
        ttk.Button(top_frame, text="اجرای Dry-Run تخصیص", command=self._start_dry_run).grid(row=1, column=3, sticky=tk.W)

        dispatcher_frame = ttk.LabelFrame(self.root, text="Dispatcher")
        dispatcher_frame.pack(fill=tk.X, **padding)
        ttk.Button(dispatcher_frame, text="شروع دیسپچر", command=self._start_dispatcher).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(dispatcher_frame, text="توقف دیسپچر", command=self._stop_dispatcher).grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(dispatcher_frame, textvariable=self.metrics_var).grid(row=0, column=2, sticky=tk.W)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, **padding)
        ttk.Label(status_frame, text="وضعیت:").pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

        events_frame = ttk.LabelFrame(self.root, text="آخرین وضعیت رویدادها")
        events_frame.pack(fill=tk.BOTH, expand=True, **padding)
        self.events_list = tk.Listbox(events_frame, height=12)
        self.events_list.pack(fill=tk.BOTH, expand=True)

        log_frame = ttk.LabelFrame(self.root, text="گزارش عملیات")
        log_frame.pack(fill=tk.BOTH, expand=True, **padding)
        self.log_text = tk.Text(log_frame, height=8, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Event queue helpers
    # ------------------------------------------------------------------
    def enqueue_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.event_queue.put(("log", (f"[{timestamp}] {message}",)))

    def enqueue_status(self, event_id: str, status: str, extra: dict[str, object]) -> None:
        self.event_queue.put(("status", (event_id, status, extra)))

    def _process_queue(self) -> None:
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "log":
                    (message,) = payload
                    self.log_text.insert(tk.END, message + "\n")
                    self.log_text.see(tk.END)
                elif kind == "status":
                    event_id, status, extra = payload
                    self._update_status(event_id, status, extra)
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._process_queue)

    def _update_status(self, event_id: str, status: str, extra: dict[str, object]) -> None:
        self._metrics.setdefault(status, 0)
        self._metrics[status] += 1
        metrics_text = " | ".join(f"{key}={value}" for key, value in self._metrics.items())
        self.metrics_var.set(metrics_text)
        description = f"{status} → {event_id} ({extra})"
        self._recent_events.append(description)
        if len(self._recent_events) > self._max_events:
            self._recent_events.pop(0)
        self.events_list.delete(0, tk.END)
        for item in self._recent_events:
            self.events_list.insert(tk.END, item)

    # ------------------------------------------------------------------
    # File parsing & dry-run
    # ------------------------------------------------------------------
    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="انتخاب فایل درخواست‌ها",
            filetypes=(
                ("JSON", "*.json"),
                ("CSV", "*.csv"),
                ("All", "*.*"),
            ),
        )
        if path:
            self.file_var.set(path)

    def _start_dry_run(self) -> None:
        file_path = self.file_var.get().strip()
        if not file_path:
            messagebox.showerror("خطا", "فایل ورودی انتخاب نشده است")
            return
        self.status_var.set("در حال اجرای Dry-Run")
        thread = threading.Thread(target=self._run_dry_run, args=(file_path,), daemon=True)
        thread.start()

    def _run_dry_run(self, file_path: str) -> None:
        try:
            allocator = build_allocator(self.database_var.get())
            requests = list(self._load_requests(Path(file_path)))
            if not requests:
                self.enqueue_log("هیچ درخواستی در فایل یافت نشد")
            for idx, request in enumerate(requests, 1):
                result: AllocationResult = allocator.allocate(request, dry_run=True)
                self.enqueue_log(
                    f"[{idx}] دانش‌آموز {request.student_id} ← منتور {request.mentor_id}: {result.status}"
                )
        except FileNotFoundError:
            messagebox.showerror("خطا", "فایل ورودی یافت نشد")
        except Exception as exc:  # pragma: no cover - GUI guard
            logger.exception("اجرای Dry-Run با خطا متوقف شد")
            messagebox.showerror("خطا", f"اجرای آزمایشی با خطا متوقف شد: {exc}")
        finally:
            self.status_var.set("آماده")

    def _load_requests(self, path: Path) -> Iterable[AllocationRequest]:
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                data = data.get("requests", [])
            if not isinstance(data, Sequence):
                raise ValueError("ساختار JSON باید شامل آرایه درخواست باشد")
            for entry in data:
                yield AllocationRequest.model_validate(entry)
        elif path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    yield AllocationRequest.model_validate(row)
        else:
            raise ValueError("فرمت فایل پشتیبانی نمی‌شود")

    # ------------------------------------------------------------------
    # Dispatcher control
    # ------------------------------------------------------------------
    def _start_dispatcher(self) -> None:
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            messagebox.showinfo("دیسپچر", "دیسپچر در حال اجراست")
            return
        self._dispatcher_stop.clear()
        self._dispatcher_thread = threading.Thread(target=self._run_dispatcher, daemon=True)
        self._dispatcher_thread.start()
        self.status_var.set("دیسپچر فعال است")

    def _run_dispatcher(self) -> None:
        try:
            engine = create_engine(self.database_var.get(), future=True)
            SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
            publisher = TkPublisher(sink=self)
            while not self._dispatcher_stop.is_set():
                session = SessionFactory()
                try:
                    dispatcher = OutboxDispatcher(
                        session=session,
                        publisher=publisher,
                        clock=SystemClock(),
                        status_hook=lambda event_id, status, extra: self.enqueue_status(event_id, status, extra),
                    )
                    sent = dispatcher.dispatch_once()
                    if sent == 0:
                        self._dispatcher_stop.wait(1.0)
                finally:
                    session.close()
        except Exception as exc:  # pragma: no cover - GUI guard
            logger.exception("اجرای دیسپچر GUI با خطا متوقف شد")
            self.enqueue_log(f"دیسپچر با خطا متوقف شد: {exc}")
        finally:
            self.status_var.set("آماده")

    def _stop_dispatcher(self) -> None:
        if self._dispatcher_thread and self._dispatcher_thread.is_alive():
            self._dispatcher_stop.set()
            self.enqueue_log("درخواست توقف دیسپچر ثبت شد")
        else:
            messagebox.showinfo("دیسپچر", "دیسپچر فعال نیست")

    # ------------------------------------------------------------------
    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        self.root.mainloop()


def main() -> None:
    gui = OperatorGUI()
    gui.run()


if __name__ == "__main__":  # pragma: no cover - manual execution
    main()
