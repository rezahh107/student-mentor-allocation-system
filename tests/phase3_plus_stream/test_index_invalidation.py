"""Tests for selection-aware invalidation in the trace filter index."""
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


def _row(idx: int, group: str, center: str, selected: bool = False) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=idx,
        mentor_id=f"M{idx}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    row.student_group = group
    row.student_center = center
    row.is_selected = selected
    return row


def test_mark_selection_dirty_only_refreshes_changed_rows() -> None:
    storage = _FakeStorage(
        [
            _row(0, "G", "C", selected=True),
            _row(1, "G", "C"),
            _row(2, "G", "C"),
            _row(3, "G", "C"),
        ]
    )
    index = TraceFilterIndex(storage)

    windows = index.apply_filters({"selected_only": True})
    assert windows == [(0, 1)]

    storage.calls.clear()
    # Warm the unfiltered window cache so we can ensure it stays valid.
    index.apply_filters({})
    assert storage.calls == []

    storage.rows[2].is_selected = True
    index.queue_selection_update(2)
    index.mark_selection_dirty()
    assert storage.calls == [2]

    storage.calls.clear()
    windows = index.apply_filters({"selected_only": True})
    assert windows == [(0, 1), (2, 3)]
    assert storage.calls == []

    storage.rows[0].is_selected = False
    index.queue_selection_update(0)
    index.mark_selection_dirty()
    assert storage.calls == [0]

    storage.calls.clear()
    windows = index.apply_filters({"selected_only": True})
    assert windows == [(2, 3)]
    assert storage.calls == []

    storage.calls.clear()
    windows = index.apply_filters({})
    assert windows == [(0, len(storage.rows))]
    assert storage.calls == []
