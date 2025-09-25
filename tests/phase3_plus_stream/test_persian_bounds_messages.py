"""Tests ensuring Persian pagination errors include totals and digit folding."""
from __future__ import annotations

from dataclasses import dataclass
from io import StringIO

import pytest

from scripts.phase3_cli import _validate_pagination
from src.ui.trace_index import TraceFilterIndex
from src.ui.trace_viewer import TraceViewerRow, render_text_ui


@dataclass
class _FakeStorage:
    rows: list[TraceViewerRow]

    def __post_init__(self) -> None:
        self.calls: list[int] = []

    def __len__(self) -> int:
        return len(self.rows)

    def get_row(self, index: int) -> TraceViewerRow:
        self.calls.append(index)
        return self.rows[index]


def _row(idx: int) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=idx,
        mentor_id=f"M{idx}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    row.student_group = "G"
    row.student_center = "C"
    row.is_selected = True
    return row


def test_validate_pagination_reports_totals_in_persian() -> None:
    rows = [_row(idx) for idx in range(1200)]
    storage = _FakeStorage(rows)
    index = TraceFilterIndex(storage)

    with pytest.raises(ValueError) as exc:
        _validate_pagination(index, page_size=50, page=30)
    message = str(exc.value)
    assert "صفحه ۳۰ معتبر نیست" in message
    assert "بیشینهٔ صفحه: ۲۴" in message
    assert "۱٬۲۰۰" in message
    assert "نزدیک‌ترین صفحهٔ مجاز: ۲۴" in message


def test_render_text_ui_reports_totals_in_persian() -> None:
    rows = [_row(idx) for idx in range(1200)]
    storage = _FakeStorage(rows)
    index = TraceFilterIndex(storage)

    buffer = StringIO()
    render_text_ui(storage, stream=buffer, limit=50, page=30, index=index)
    output = buffer.getvalue().strip()
    assert "صفحه ۳۰ معتبر نیست" in output
    assert "بیشینهٔ صفحه: ۲۴" in output
    assert "۱٬۲۰۰" in output
    assert "نزدیک‌ترین صفحهٔ مجاز: ۲۴" in output
