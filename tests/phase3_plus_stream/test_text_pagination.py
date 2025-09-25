"""Tests for headless text pagination."""
from __future__ import annotations

from io import StringIO

from src.ui.trace_viewer import (
    TraceViewerRow,
    TraceViewerStorageWriter,
    render_text_ui,
)


def _row(index: int, selected: bool = True) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=index,
        mentor_id=f"M{index}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    row.student_center = f"C{index % 3}"
    row.student_group = f"G{index % 4}"
    row.is_selected = selected
    return row


def test_render_text_ui_paginated_window() -> None:
    writer = TraceViewerStorageWriter()
    for idx in range(6):
        writer.append_rows([_row(idx)])
    storage = writer.finalize()

    buffer = StringIO()
    render_text_ui(storage, stream=buffer, limit=2, page=2)
    lines = buffer.getvalue().strip().splitlines()
    storage.cleanup()

    assert lines[0].startswith("شاخص")
    assert any("#2" in line for line in lines)
    assert any("#3" in line for line in lines)
    assert not any("#0" in line for line in lines)


def test_render_text_ui_missing_page_message() -> None:
    writer = TraceViewerStorageWriter()
    writer.append_rows([_row(0)])
    storage = writer.finalize()

    buffer = StringIO()
    render_text_ui(storage, stream=buffer, limit=5, page=3)

    storage.cleanup()
    output = buffer.getvalue()
    assert "صفحه ۳ معتبر نیست" in output
    assert "بیشینهٔ صفحه: ۱" in output
