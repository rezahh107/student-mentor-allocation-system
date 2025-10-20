from __future__ import annotations

import io

import pytest

from sma.ui.trace_viewer import (
    PAGE_SIZE,
    TraceViewerApp,
    TraceViewerRow,
    TraceViewerStorageWriter,
    render_text_ui,
)


def _make_row(index: int) -> TraceViewerRow:
    return TraceViewerRow(
        student_index=index,
        mentor_id=str(1000 + index),
        mentor_type="NORMAL",
        passed=index % 2 == 0,
        occupancy_ratio=0.5,
        current_load=1,
        trace=[{"code": "GENDER_MATCH", "passed": True, "details": {}}],
        student_group=f"G{index % 5}",
        student_center=f"C{index % 3}",
        is_selected=index % 7 == 0,
    )


def test_virtualized_gui_maintains_window() -> None:
    tk = pytest.importorskip("tkinter")

    writer = TraceViewerStorageWriter()
    total_rows = PAGE_SIZE + 120
    for idx in range(total_rows):
        writer.append_rows([_make_row(idx)])
    storage = writer.finalize()
    try:
        root = tk.Tk()
    except Exception:
        storage.cleanup()
        pytest.skip("Tkinter root unavailable")
    try:
        app = TraceViewerApp(root, storage)
        root.update_idletasks()
        assert len(app._page_rows) <= PAGE_SIZE
        assert len(storage._cache) <= PAGE_SIZE  # initial load
        app._load_next_page()
        root.update_idletasks()
        assert len(app._page_rows) <= PAGE_SIZE
        assert len(storage._cache) <= PAGE_SIZE + PAGE_SIZE  # two pages cached
        app.group_entry.insert(0, "G1")
        app._apply_filter()
        root.update_idletasks()
        assert all("G1" in row.student_group for row in app._page_rows)
    finally:
        root.destroy()
        storage.cleanup()


def test_text_ui_renders_selection(tmp_path) -> None:
    writer = TraceViewerStorageWriter()
    for index in range(5):
        writer.append_rows([_make_row(index)])
    storage = writer.finalize()
    buffer = io.StringIO()
    try:
        render_text_ui(storage, stream=buffer, limit=3)
        output = buffer.getvalue()
        assert "منتور" in output
        assert "#0" in output
    finally:
        storage.cleanup()
