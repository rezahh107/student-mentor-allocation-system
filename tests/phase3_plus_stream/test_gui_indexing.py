"""Tests for incremental GUI filter indexing."""
from __future__ import annotations

from dataclasses import dataclass

from sma.ui.trace_index import TraceFilterIndex
from sma.ui.trace_viewer import TraceViewerRow


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


def _row(student_index: int, group: str, center: str) -> TraceViewerRow:
    row = TraceViewerRow(
        student_index=student_index,
        mentor_id=f"M{student_index}",
        mentor_type="NORMAL",
        passed=True,
        occupancy_ratio=0.5,
        current_load=1,
    )
    row.student_group = group
    row.student_center = center
    return row


def test_index_returns_windows_and_intersections() -> None:
    storage = _FakeStorage(
        [
            _row(0, "G1", "C1"),
            _row(1, "G2", "C1"),
            _row(2, "G1", "C2"),
            _row(3, "G1", "C1"),
            _row(4, "G2", "C1"),
        ]
    )
    index = TraceFilterIndex(storage)

    windows = index.apply_filters({"group_code": "G1"})
    assert windows == [(0, 1), (2, 4)]
    assert storage.calls == [0, 1, 2, 3, 4]

    storage.calls.clear()
    windows = index.apply_filters({"group_code": "G1", "reg_center": "C1"})
    assert windows == [(0, 1), (3, 4)]
    assert storage.calls == []


def test_index_incremental_extension() -> None:
    storage = _FakeStorage([
        _row(0, "G1", "C1"),
        _row(1, "G1", "C2"),
    ])
    index = TraceFilterIndex(storage)

    first_windows = index.apply_filters({"group_code": "G1"})
    assert first_windows == [(0, 2)]
    assert storage.calls == [0, 1]

    storage.calls.clear()
    storage.rows.extend([
        _row(2, "G2", "C1"),
        _row(3, "G1", "C1"),
    ])

    second_windows = index.apply_filters({"reg_center": "C1"})
    assert second_windows == [(0, 1), (2, 4)]
    # Only the new rows should be indexed on the second call.
    assert storage.calls == [2, 3]
