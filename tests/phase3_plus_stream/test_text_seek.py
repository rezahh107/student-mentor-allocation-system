from __future__ import annotations

from io import StringIO

from src.ui.trace_index import TraceFilterIndex
from src.ui.trace_viewer import TraceViewerRow, render_text_ui


class _LoggingStorage:
    def __init__(self, rows: list[TraceViewerRow]) -> None:
        self._rows = rows
        self.calls: list[int] = []

    def __len__(self) -> int:
        return len(self._rows)

    def get_row(self, index: int) -> TraceViewerRow:
        self.calls.append(index)
        return self._rows[index]


def _row(index: int) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=index,
        mentor_id=f"M{index}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    row.is_selected = True
    row.student_center = f"C{index % 3}"
    row.student_group = f"G{index % 5}"
    return row


def test_seek_page_deep_window_avoids_linear_scan() -> None:
    total_rows = 11000
    rows = [_row(i) for i in range(total_rows)]
    storage = _LoggingStorage(rows)
    index = TraceFilterIndex(storage)

    index.apply_filters({"selected_only": True})
    assert len(storage.calls) == total_rows
    storage.calls.clear()

    indices = list(index.seek_page({"selected_only": True}, page=200, page_size=50))
    assert len(indices) == 50
    assert indices[0] == 9950
    assert indices[-1] == 9999
    assert storage.calls == []

    buffer = StringIO()
    render_text_ui(storage, stream=buffer, limit=50, page=200, index=index)
    assert len(storage.calls) == 50
    output = buffer.getvalue()
    assert "#9950" in output
    assert "#9999" in output
