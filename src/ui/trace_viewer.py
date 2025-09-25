"""Virtualised trace viewer with Tkinter UI and text fallback."""
from __future__ import annotations

import json
import sys
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

try:  # pragma: no cover - tkinter availability checked at runtime
    import tkinter as tk
    from tkinter import ttk
except Exception as exc:  # pragma: no cover - Tkinter optional in CI
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    TK_IMPORT_ERROR = exc
else:  # pragma: no cover - stored for reporting
    TK_IMPORT_ERROR = None

from src.phase3_allocation.engine import AllocationTraceEntry
from src.tools.export_excel_safe import normalize_cell
from src.ui.trace_index import TraceFilterIndex

PAGE_SIZE = 200
CACHE_LIMIT = 400
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class _CompatItems:
    """Minimal holder to expose `items` for legacy tests."""

    def __init__(self) -> None:
        self.items: List[str] = []


class _CompatButton:
    """Fallback button with no-op geometry methods."""

    def __init__(self, command) -> None:
        self.command = command

    def pack(self, **_kwargs) -> None:
        return None

    def invoke(self) -> None:
        if self.command:
            self.command()


@dataclass
class TraceViewerRow:
    """Representation of a single mentor evaluation for UI layers."""

    student_index: int
    mentor_id: str
    mentor_type: str
    passed: bool
    occupancy_ratio: float | None
    current_load: int | None
    trace: List[dict[str, object]] = field(default_factory=list)
    ranking_key: tuple[float, int, int] | None = None
    student_group: str = ""
    student_center: str = ""
    is_selected: bool = False

    @classmethod
    def from_engine_entry(
        cls, entry: AllocationTraceEntry, *, student_index: int
    ) -> "TraceViewerRow":
        mentor_id = normalize_cell(getattr(entry.mentor, "mentor_id", "") if entry.mentor else "")
        mentor_type = normalize_cell(getattr(entry.mentor, "mentor_type", "") if entry.mentor else "")
        occupancy_ratio = entry.ranking_key[0] if entry.ranking_key else None
        current_load = entry.ranking_key[1] if entry.ranking_key else None
        return cls(
            student_index=student_index,
            mentor_id=mentor_id,
            mentor_type=mentor_type,
            passed=entry.passed,
            occupancy_ratio=occupancy_ratio,
            current_load=current_load,
            trace=[dict(item) for item in entry.trace],
            ranking_key=entry.ranking_key,
        )

    def to_serialisable(self) -> dict[str, object]:
        """Convert the row to a JSON-friendly mapping."""

        return {
            "student_index": self.student_index,
            "mentor_id": self.mentor_id,
            "mentor_type": self.mentor_type,
            "passed": self.passed,
            "occupancy_ratio": self.occupancy_ratio,
            "current_load": self.current_load,
            "trace": self.trace,
            "ranking_key": list(self.ranking_key) if self.ranking_key else None,
            "student_group": self.student_group,
            "student_center": self.student_center,
            "is_selected": self.is_selected,
        }

    @classmethod
    def from_serialisable(cls, payload: dict[str, object]) -> "TraceViewerRow":
        """Reconstruct the row from stored JSON."""

        ranking = payload.get("ranking_key")
        ranking_tuple = tuple(ranking) if isinstance(ranking, list) else None
        return cls(
            student_index=int(payload.get("student_index", 0)),
            mentor_id=str(payload.get("mentor_id", "")),
            mentor_type=str(payload.get("mentor_type", "")),
            passed=bool(payload.get("passed", False)),
            occupancy_ratio=(
                float(payload["occupancy_ratio"])
                if payload.get("occupancy_ratio") is not None
                else None
            ),
            current_load=(
                int(payload["current_load"])
                if payload.get("current_load") is not None
                else None
            ),
            trace=[dict(item) for item in payload.get("trace", [])],
            ranking_key=tuple(ranking_tuple) if ranking_tuple else None,
            student_group=str(payload.get("student_group", "")),
            student_center=str(payload.get("student_center", "")),
            is_selected=bool(payload.get("is_selected", False)),
        )

    def display_values(self) -> tuple[str, str, str, str]:
        """Return tuple of values for Treeview display."""

        status = "قبول" if self.passed else "رد"
        ratio_text = "-" if self.occupancy_ratio is None else f"{self.occupancy_ratio:.2f}"
        load_text = "-" if self.current_load is None else str(self.current_load)
        return (
            f"#{self.student_index}",
            self.mentor_id or "نامشخص",
            status,
            f"{ratio_text}/{load_text}",
        )


class TraceViewerStorageWriter:
    """Persist trace rows lazily to a temporary file for virtualised viewing."""

    def __init__(self) -> None:
        self._file = tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", newline="", delete=False
        )
        self._offsets: List[int] = []

    def append_rows(self, rows: Iterable[TraceViewerRow]) -> None:
        for row in rows:
            offset = self._file.tell()
            json.dump(row.to_serialisable(), self._file, ensure_ascii=False)
            self._file.write("\n")
            self._offsets.append(offset)

    def finalize(self) -> "TraceViewerStorage":
        self._file.flush()
        path = Path(self._file.name)
        self._file.close()
        return TraceViewerStorage(path=path, offsets=list(self._offsets))


class TraceViewerStorage:
    """Random-access storage with a small in-memory cache for GUI pages."""

    def __init__(self, *, path: Path, offsets: List[int]) -> None:
        self._path = path
        self._offsets = offsets
        self._cache: "OrderedDict[int, TraceViewerRow]" = OrderedDict()

    def __len__(self) -> int:
        return len(self._offsets)

    @property
    def path(self) -> Path:
        return self._path

    def cleanup(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except Exception:
            pass

    def get_row(self, index: int) -> TraceViewerRow:
        if index < 0 or index >= len(self._offsets):
            raise IndexError("شناسه ردیف خارج از محدوده است.")
        cached = self._cache.get(index)
        if cached is not None:
            self._cache.move_to_end(index)
            return cached
        offset = self._offsets[index]
        with self._path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            line = handle.readline()
        payload = json.loads(line) if line else {}
        row = TraceViewerRow.from_serialisable(payload)
        self._cache[index] = row
        if len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)
        return row

    def page(self, start: int, size: int) -> List[TraceViewerRow]:
        end = min(start + size, len(self._offsets))
        return [self.get_row(index) for index in range(start, end)]

    def iter_rows(self) -> Iterator[TraceViewerRow]:
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                yield TraceViewerRow.from_serialisable(payload)

    def iter_selected(self) -> Iterator[TraceViewerRow]:
        for row in self.iter_rows():
            if row.is_selected:
                yield row


class _InMemoryStorage:
    """Simple in-memory storage to maintain backward compatibility for tests."""

    def __init__(self, rows: Iterable[TraceViewerRow]) -> None:
        self._rows = [row for row in rows]

    def __len__(self) -> int:
        return len(self._rows)

    def get_row(self, index: int) -> TraceViewerRow:
        return self._rows[index]

    def page(self, start: int, size: int) -> List[TraceViewerRow]:
        return self._rows[start : start + size]

    def iter_rows(self) -> Iterator[TraceViewerRow]:
        yield from self._rows

    def iter_selected(self) -> Iterator[TraceViewerRow]:
        for row in self._rows:
            if row.is_selected:
                yield row

    def cleanup(self) -> None:
        return None


class TraceViewerApp:
    """Minimal Tkinter UI to inspect allocation traces with paging."""

    def __init__(
        self,
        root: "tk.Misc",
        storage: TraceViewerStorage,
        *,
        tk_module: object | None = None,
        page_size: int = PAGE_SIZE,
        initial_page: int = 1,
        index: TraceFilterIndex | None = None,
    ) -> None:
        if tk is None and tk_module is None:
            raise RuntimeError("کتابخانه Tkinter در دسترس نیست.")
        self.tk = tk_module or tk
        self.ttk = ttk if tk_module is None else getattr(tk_module, "ttk", None)
        self.root = root
        if isinstance(storage, TraceViewerStorage):
            self.storage = storage
        else:
            self.storage = _InMemoryStorage(storage)
        self._index = index or TraceFilterIndex(self.storage)
        total = len(self.storage)
        self._filtered_windows: List[Tuple[int, int]] = [(0, total)] if total else []
        self._filtered_count = total
        self._page_size = page_size if page_size > 0 else PAGE_SIZE
        self._current_page = max(0, initial_page - 1)
        self._filter_job: int | None = None
        self._filter_dirty = False
        self._page_rows: List[TraceViewerRow] = []
        self._visible_rows: List[TraceViewerRow] = []
        self._use_treeview = self.ttk is not None and hasattr(self.ttk, "Treeview")
        self._build_ui()
        self._schedule_page_load(self._current_page)

    @classmethod
    def create(
        cls,
        storage: TraceViewerStorage,
        *,
        page_size: int = PAGE_SIZE,
        initial_page: int = 1,
        index: TraceFilterIndex | None = None,
    ) -> "TraceViewerApp":
        if tk is None:
            raise RuntimeError("قابلیت گرافیکی در این محیط فعال نیست.") from TK_IMPORT_ERROR
        try:
            root = tk.Tk()
        except Exception as exc:
            raise RuntimeError("امکان ایجاد رابط کاربری وجود ندارد.") from exc
        root.title("نمایش ردگیری تخصیص فاز ۳")
        root.geometry("960x640")
        return cls(
            root,
            storage,
            page_size=page_size,
            initial_page=initial_page,
            index=index,
        )

    def start(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        label_font = {"font": ("Tahoma", 10)}
        filter_frame = self.tk.Frame(self.root)
        filter_frame.pack(fill="x", padx=8, pady=4)

        self.tk.Label(filter_frame, text="فیلتر گروه", **label_font).pack(side="left", padx=4)
        self.group_entry = self.tk.Entry(filter_frame)
        self.group_entry.pack(side="left", padx=4)
        self.group_entry.bind("<KeyRelease>", self._on_filter_change)

        self.tk.Label(filter_frame, text="فیلتر مرکز", **label_font).pack(side="left", padx=4)
        self.center_entry = self.tk.Entry(filter_frame)
        self.center_entry.pack(side="left", padx=4)
        self.center_entry.bind("<KeyRelease>", self._on_filter_change)

        list_frame = self.tk.Frame(self.root)
        list_frame.pack(fill="both", expand=True, padx=8, pady=4)

        if self._use_treeview:
            columns = ("student", "mentor", "status", "ratio")
            self.tree = self.ttk.Treeview(list_frame, columns=columns, show="headings", height=18)
            self.tree.heading("student", text="دانش‌آموز")
            self.tree.heading("mentor", text="منتور")
            self.tree.heading("status", text="وضعیت")
            self.tree.heading("ratio", text="نسبت/ظرفیت")
            self.tree.column("student", width=120, anchor="center")
            self.tree.column("mentor", width=180)
            self.tree.column("status", width=120, anchor="center")
            self.tree.column("ratio", width=140, anchor="center")
            self.tree.pack(side="left", fill="both", expand=True)
            scrollbar = self.tk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
            scrollbar.pack(side="right", fill="y")
            self.tree.configure(yscrollcommand=scrollbar.set)
            self.listbox = _CompatItems()
        else:
            self.tree = None
            self.listbox = self.tk.Listbox(list_frame)
            self.listbox.pack(side="left", fill="both", expand=True)
            self.listbox.bind("<<ListboxSelect>>", self._on_select)
            scrollbar = self.tk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
            scrollbar.pack(side="right", fill="y")
            self.listbox.configure(yscrollcommand=scrollbar.set)

        control_frame = self.tk.Frame(self.root)
        control_frame.pack(fill="x", padx=8, pady=4)
        if hasattr(self.tk, "Button"):
            self.prev_button = self.tk.Button(control_frame, text="صفحه قبل", command=self._load_previous_page)
            self.prev_button.pack(side="left", padx=4)
            self.next_button = self.tk.Button(control_frame, text="صفحه بعد", command=self._load_next_page)
            self.next_button.pack(side="left", padx=4)
        else:
            self.prev_button = _CompatButton(self._load_previous_page)
            self.next_button = _CompatButton(self._load_next_page)

        trace_frame = self.tk.Frame(self.root)
        trace_frame.pack(fill="both", expand=False, padx=8, pady=4)
        self.trace_text = self.tk.Text(trace_frame, height=12)
        self.trace_text.pack(fill="both", expand=True)
        self.trace_text.configure(state="disabled")

        if self._use_treeview:
            self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.root.bind("<Return>", self._on_enter)
        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.bind("<Up>", self._on_up)
        self.root.bind("<Down>", self._on_down)
        self.root.bind("<Prior>", self._on_page_up)
        self.root.bind("<Next>", self._on_page_down)

    def _schedule_page_load(self, page: int) -> None:
        max_page = 0
        if self._filtered_count > 0 and self._page_size > 0:
            max_page = max(0, (self._filtered_count - 1) // self._page_size)
        self._current_page = min(max_page, max(0, page))
        if self._filter_job is None:
            self._filter_job = self.root.after(0, self._load_page)
        else:
            if hasattr(self.root, "after_cancel"):
                try:
                    self.root.after_cancel(self._filter_job)
                except Exception:
                    pass
            self._filter_job = self.root.after(0, self._load_page)

    def _load_page(self) -> None:
        if self._current_page < 0:
            self._current_page = 0
        start_index = self._current_page * self._page_size
        indices = self._page_window_indices(start_index, self._page_size)
        rows = [self.storage.get_row(index) for index in indices]
        self._page_rows = rows
        self._visible_rows = rows
        if self._use_treeview:
            self.tree.delete(*self.tree.get_children())
            compat_items: List[str] = []
            for row in rows:
                values = row.display_values()
                tags = ("selected",) if row.is_selected else ()
                display = "★ " + " | ".join(values) if row.is_selected else " | ".join(values)
                compat_items.append(display)
                self.tree.insert(
                    "",
                    "end",
                    iid=str(row.student_index) + ":" + row.mentor_id,
                    values=values,
                    tags=tags,
                )
            self.listbox.items = compat_items
            if rows:
                self.tree.selection_set(self.tree.get_children()[0])
                self._show_entry(0)
            else:
                self._clear_trace()
            self.tree.tag_configure("selected", background="#d9edf7")
        else:
            self.listbox.delete(0, self.tk.END)
            for row in rows:
                display = row.display_values()
                text = " | ".join(display)
                if row.is_selected:
                    text = "★ " + text
                self.listbox.insert(self.tk.END, text)
            if rows:
                self.listbox.selection_set(0)
                self._show_entry(0)
            else:
                self._clear_trace()
        self._filter_job = None

    def refresh_after_selection_toggle(self, indices: Iterable[int]) -> None:
        """Refresh visible windows after selection state toggles.

        Args:
            indices: Absolute indices whose selection state changed. Only the
                active page is reloaded so pagination remains O(window).
        """

        for index in indices:
            self._index.queue_selection_update(int(index))
        self._index.mark_selection_dirty()
        filters = {
            "group_code": self.group_entry.get(),
            "reg_center": self.center_entry.get(),
        }
        self._filtered_windows = self._index.apply_filters(filters)
        self._filtered_count = self._index.last_count
        max_page = 0
        if self._filtered_count and self._page_size:
            max_page = max(0, (self._filtered_count - 1) // self._page_size)
        if self._current_page > max_page:
            self._current_page = max_page
        self._load_page()

    def _on_filter_change(self, _event: object) -> None:
        self._filter_dirty = True
        if not self._use_treeview:
            self._apply_filter()
            return
        if self._filter_job is None:
            self._filter_job = self.root.after(200, self._apply_filter)

    def _apply_filter(self) -> None:
        if not self._filter_dirty:
            return
        self._filter_job = None
        self._filter_dirty = False
        filters = {
            "group_code": self.group_entry.get(),
            "reg_center": self.center_entry.get(),
        }
        windows = self._index.apply_filters(filters)
        self._filtered_windows = windows
        self._filtered_count = self._index.last_count
        self._schedule_page_load(0)

    def _load_previous_page(self) -> None:
        if self._current_page > 0:
            self._schedule_page_load(self._current_page - 1)

    def _load_next_page(self) -> None:
        max_page = max(0, (self._filtered_count - 1) // self._page_size)
        if self._current_page < max_page:
            self._schedule_page_load(self._current_page + 1)

    def _on_select(self, _event: object) -> None:
        index = self._current_selection_index()
        if index is None:
            return
        self._show_entry(index)

    def _on_enter(self, _event: object) -> None:
        index = self._current_selection_index()
        if index is not None:
            self._show_entry(index)
        elif self._page_rows:
            if self._use_treeview:
                self.tree.selection_set(self.tree.get_children()[0])
            else:
                self.listbox.selection_set(0)
            self._show_entry(0)

    def _on_up(self, _event: object) -> None:
        index = self._current_selection_index()
        if index is None:
            return
        new_index = max(0, index - 1)
        self._set_selection(new_index)
        self._show_entry(new_index)

    def _on_down(self, _event: object) -> None:
        index = self._current_selection_index()
        if index is None:
            return
        new_index = min(len(self._page_rows) - 1, index + 1)
        self._set_selection(new_index)
        self._show_entry(new_index)

    def _on_page_up(self, _event: object) -> None:
        self._load_previous_page()

    def _on_page_down(self, _event: object) -> None:
        self._load_next_page()

    def _clear_trace(self) -> None:
        self.trace_text.configure(state="normal")
        self.trace_text.delete("1.0", self.tk.END)
        self.trace_text.configure(state="disabled")

    def _show_entry(self, index: int) -> None:
        if index < 0 or index >= len(self._page_rows):
            return
        row = self._page_rows[index]
        self.trace_text.configure(state="normal")
        self.trace_text.delete("1.0", self.tk.END)
        for trace in row.trace:
            status = "قبول" if trace.get("passed") else "رد"
            details = trace.get("details", {})
            detail_parts = [
                f"{key}={normalize_cell(value)}" for key, value in details.items()
            ]
            details_text = ", ".join(detail_parts) if detail_parts else ""
            line = f"{trace.get('code')}: {status}"
            if details_text:
                line += f" ({details_text})"
            self.trace_text.insert(self.tk.END, line + "\n")
        self.trace_text.configure(state="disabled")

    def _current_selection_index(self) -> int | None:
        if self._use_treeview:
            selection = self.tree.selection()
            if not selection:
                return None
            return self.tree.index(selection[0])
        if hasattr(self.listbox, "curselection"):
            selection = self.listbox.curselection()
            if selection:
                return selection[0]
        return None

    def _page_window_indices(self, start: int, size: int) -> List[int]:
        if start < 0 or size <= 0:
            return []
        remaining = size
        offset = start
        indices: List[int] = []
        for window_start, window_end in self._filtered_windows:
            window_size = window_end - window_start
            if offset >= window_size:
                offset -= window_size
                continue
            absolute_start = window_start + offset
            take = min(remaining, window_end - absolute_start)
            indices.extend(range(absolute_start, absolute_start + take))
            remaining -= take
            offset = 0
            if remaining <= 0:
                break
        return indices

    def _set_selection(self, index: int) -> None:
        if self._use_treeview:
            children = self.tree.get_children()
            if 0 <= index < len(children):
                self.tree.selection_set(children[index])
        else:
            if hasattr(self.listbox, "selection_set"):
                self.listbox.selection_set(index)


def render_text_ui(
    storage: TraceViewerStorage,
    *,
    stream=None,
    limit: int = 20,
    page: int = 1,
    index: TraceFilterIndex | None = None,
) -> None:
    """Render a console table for selected rows when Tkinter is unavailable."""

    out_stream = stream or sys.stdout
    if limit <= 0:
        raise ValueError("اندازه صفحه باید بزرگ‌تر از صفر باشد.")
    if page <= 0:
        raise ValueError("شماره صفحه باید بزرگ‌تر از صفر باشد.")
    page_size = int(limit)
    page_number = int(page)

    trace_index = index or TraceFilterIndex(storage)
    stats = trace_index.validate_page({"selected_only": True}, page_size)
    total_selected = stats["total_rows"]
    total_pages = stats["total_pages"]

    header = (
        "شاخص",
        "منتور",
        "نوع",
        "نسبت",
        "مرکز",
        "گروه",
    )

    if total_selected == 0:
        out_stream.write("هیچ تخصیص موفقی یافت نشد.\n")
        return

    if page_number > total_pages:
        nearest = total_pages if total_pages > 0 else 1
        message = (
            f"صفحه { _to_persian_number(page_number) } معتبر نیست؛ "
            f"بیشینهٔ صفحه: {_to_persian_number(total_pages)} "
            f"({_to_persian_number(total_selected)} ردیف)."
        )
        if total_pages > 0:
            message += f" نزدیک‌ترین صفحهٔ مجاز: {_to_persian_number(nearest)}."
        out_stream.write(message + "\n")
        return

    iterator = trace_index.seek_page({"selected_only": True}, page_number, page_size)
    indices = list(iterator)
    if not indices:
        nearest = total_pages if total_pages > 0 else 1
        message = (
            f"صفحه { _to_persian_number(page_number) } معتبر نیست؛ "
            f"بیشینهٔ صفحه: {_to_persian_number(total_pages)} "
            f"({_to_persian_number(total_selected)} ردیف)."
        )
        if total_pages > 0:
            message += f" نزدیک‌ترین صفحهٔ مجاز: {_to_persian_number(nearest)}."
        out_stream.write(message + "\n")
        return

    out_stream.write(" | ".join(header) + "\n")
    out_stream.write("-" * 60 + "\n")

    for index_value in indices:
        row = storage.get_row(index_value)
        if not row.is_selected:
            continue
        ratio_text = "-" if row.occupancy_ratio is None else f"{row.occupancy_ratio:.2f}"
        line = " | ".join(
            [
                f"#{row.student_index}",
                row.mentor_id or "نامشخص",
                row.mentor_type or "-",
                ratio_text,
                row.student_center or "-",
                row.student_group or "-",
            ]
        )
        out_stream.write(line + "\n")



__all__ = [
    "TraceViewerRow",
    "TraceViewerStorage",
    "TraceViewerStorageWriter",
    "TraceViewerApp",
    "render_text_ui",
    "PAGE_SIZE",
]


def _to_persian_number(value: int) -> str:
    """Convert integers to Persian digits with thousands separators."""

    formatted = f"{value:,}".replace(",", "٬")
    return formatted.translate(_PERSIAN_DIGITS)
