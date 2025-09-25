"""Tests for pagination validation using cached index windows."""
from __future__ import annotations

from dataclasses import dataclass

from src.ui.trace_index import TraceFilterIndex
from src.ui.trace_viewer import TraceViewerRow


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


def _row(idx: int, group: str) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=idx,
        mentor_id=f"M{idx}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    row.student_group = group
    row.is_selected = idx % 2 == 0
    return row


def test_validate_page_reuses_cached_windows() -> None:
    rows = [_row(idx, "G1" if idx < 3 else "G2") for idx in range(6)]
    storage = _FakeStorage(rows)
    index = TraceFilterIndex(storage)

    windows = index.apply_filters({"group_code": "G1"})
    assert windows == [(0, 3)]
    assert storage.calls == [0, 1, 2, 3, 4, 5]

    storage.calls.clear()
    stats = index.validate_page({"group_code": "G1"}, page_size=2)
    assert stats == {"total_rows": 3, "total_pages": 2}
    assert storage.calls == []
