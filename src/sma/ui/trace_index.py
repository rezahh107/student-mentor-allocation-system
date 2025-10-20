"""Lazy filter index for trace viewer storage."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Protocol,
    Set,
    Tuple,
)

if TYPE_CHECKING:  # pragma: no cover - imported for type hints only
    from sma.ui.trace_viewer import TraceViewerRow

from sma.tools.export_excel_safe import normalize_cell


class TraceStorageProtocol(Protocol):
    """Protocol describing the minimal storage API needed for indexing."""

    def __len__(self) -> int:  # pragma: no cover - protocol definition
        """Return the number of stored rows."""

    def get_row(self, index: int) -> "TraceViewerRow":  # pragma: no cover - protocol definition
        """Retrieve a row by index."""


@dataclass(frozen=True)
class _CacheEntry:
    """Container holding cached filter windows."""

    generation: int
    windows: Tuple[Tuple[int, int], ...]
    count: int


@dataclass
class TraceFilterIndex:
    """Incremental inverted index for trace viewer filters.

    The index lazily scans the underlying storage as filters are applied so that
    large datasets (>= 100k rows) do not require a full upfront pass. Filtering
    results are returned as windows ``(start, end)`` with ``end`` being
    exclusive, enabling callers to request only the rows belonging to the
    visible window.
    """

    storage: TraceStorageProtocol

    def __post_init__(self) -> None:
        self._group_index: Dict[str, List[int]] = {}
        self._center_index: Dict[str, List[int]] = {}
        self._selected_indices: List[int] = []
        self._indexed_upto = 0
        self._last_count = 0
        self._window_cache: MutableMapping[Tuple[str, str, bool], _CacheEntry] = {}
        self._selection_state: Dict[int, bool] = {}
        self._pending_selection_updates: Set[int] = set()
        self._cache_generation = 0

    def apply_filters(self, filters: Mapping[str, object]) -> List[Tuple[int, int]]:
        """Return filtered row windows based on provided criteria.

        Args:
            filters: Mapping with optional ``group_code`` and ``reg_center``
                values supplied by UI elements. Empty or null-like values are
                ignored.

        Returns:
            Sorted non-overlapping windows represented by ``(start, end)``
            tuples. ``end`` is exclusive. When no filters are provided, a single
            window spanning the entire storage is returned. If no rows match,
            an empty list is produced.
        """

        entry = self._get_cache_entry(filters)
        return list(entry.windows)

    def validate_page(
        self, filters: Mapping[str, object], page_size: int
    ) -> Dict[str, int]:
        """Return pagination metadata for a filter set without re-scanning rows.

        Args:
            filters: Filter mapping understood by :meth:`apply_filters`.
            page_size: Positive number of rows per page.

        Returns:
            Dictionary containing ``total_rows`` and ``total_pages`` keys.

        Raises:
            ValueError: If ``page_size`` is not positive.
        """

        if page_size <= 0:
            raise ValueError("اندازه صفحه باید بزرگ‌تر از صفر باشد.")
        entry = self._get_cache_entry(filters)
        total_rows = entry.count
        total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
        return {"total_rows": total_rows, "total_pages": total_pages}

    def seek_page(
        self, filters: Mapping[str, object], page: int, page_size: int
    ) -> Iterator[int]:
        """Yield absolute indices for the requested page lazily.

        Args:
            filters: Filtering options understood by :meth:`apply_filters`.
            page: One-based page number to materialise.
            page_size: Number of rows per page.

        Yields:
            Absolute indices into the storage for the requested page.

        Raises:
            ValueError: If ``page`` or ``page_size`` are invalid or point to a
            page outside the available result range.
        """

        if page_size <= 0:
            raise ValueError("اندازه صفحه باید بزرگ‌تر از صفر باشد.")
        if page <= 0:
            raise ValueError("شماره صفحه باید بزرگ‌تر از صفر باشد.")

        entry = self._get_cache_entry(filters)
        windows = entry.windows
        total = entry.count
        if total == 0:
            if page > 1:
                raise ValueError("صفحهٔ درخواستی خارج از محدوده است.")
            return iter(())

        max_page = (total + page_size - 1) // page_size
        if page > max_page:
            raise ValueError("صفحهٔ درخواستی خارج از محدوده است.")

        skip = (page - 1) * page_size
        remaining = page_size

        def _generator() -> Iterator[int]:
            nonlocal skip, remaining
            for start, end in windows:
                window_size = end - start
                if skip >= window_size:
                    skip -= window_size
                    continue
                index = start + skip
                while index < end and remaining > 0:
                    yield index
                    index += 1
                    remaining -= 1
                skip = 0
                if remaining <= 0:
                    break

        return _generator()

    def _ensure_indexed(self, target_size: int) -> None:
        added = False
        while self._indexed_upto < target_size:
            row = self.storage.get_row(self._indexed_upto)
            group_key = self._prepare_key(getattr(row, "student_group", ""))
            center_key = self._prepare_key(getattr(row, "student_center", ""))
            self._group_index.setdefault(group_key, []).append(self._indexed_upto)
            self._center_index.setdefault(center_key, []).append(self._indexed_upto)
            is_selected = bool(getattr(row, "is_selected", False))
            if is_selected:
                self._selected_indices.append(self._indexed_upto)
            self._selection_state[self._indexed_upto] = is_selected
            self._indexed_upto += 1
            added = True
        if added:
            self._cache_generation += 1

    def queue_selection_update(self, index: int) -> None:
        """Queue a row index whose selection state has toggled.

        Args:
            index: Absolute storage index whose ``is_selected`` flag changed.
        """

        if index < 0:
            return
        self._pending_selection_updates.add(index)

    def mark_selection_dirty(self) -> None:
        """Refresh selection indexes for queued rows and purge relevant caches.

        Only caches that rely on ``selected_only`` filters are invalidated so
        other filter windows remain warm.
        """

        if not self._pending_selection_updates:
            return
        updated = False
        for index in sorted(self._pending_selection_updates):
            self._ensure_indexed(index + 1)
            if index >= len(self.storage):
                continue
            row = self.storage.get_row(index)
            new_state = bool(getattr(row, "is_selected", False))
            old_state = self._selection_state.get(index, False)
            if new_state == old_state:
                continue
            if new_state:
                self._add_selected_index(index)
            else:
                self._remove_selected_index(index)
            self._selection_state[index] = new_state
            updated = True
        self._pending_selection_updates.clear()
        if updated:
            keys_to_remove = [key for key in self._window_cache if key[2]]
            for key in keys_to_remove:
                self._window_cache.pop(key, None)
            self._last_count = 0

    @staticmethod
    def _prepare_key(value: object | None) -> str:
        text = normalize_cell(value).strip()
        return text

    def _build_full_window(self) -> List[Tuple[int, int]]:
        total = len(self.storage)
        if total == 0:
            return []
        return [(0, total)]

    def _get_cache_entry(self, filters: Mapping[str, object]) -> _CacheEntry:
        key = self._filters_key(filters)
        entry = self._window_cache.get(key)
        if entry and entry.generation == self._cache_generation:
            self._last_count = entry.count
            return entry
        windows = self._compute_windows(filters)
        count = sum(end - start for start, end in windows)
        entry = _CacheEntry(self._cache_generation, tuple(windows), count)
        self._window_cache[key] = entry
        self._last_count = count
        return entry

    def _compute_windows(self, filters: Mapping[str, object]) -> List[Tuple[int, int]]:
        self._ensure_indexed(len(self.storage))
        group_value = self._prepare_key(filters.get("group_code"))
        center_value = self._prepare_key(filters.get("reg_center"))
        selected_only = bool(filters.get("selected_only"))

        candidates: List[List[int]] = []
        if group_value:
            candidates.append(list(self._group_index.get(group_value, [])))
        if center_value:
            candidates.append(list(self._center_index.get(center_value, [])))
        if selected_only:
            candidates.append(list(self._selected_indices))

        if not candidates:
            return self._build_full_window()

        current = candidates[0]
        for other in candidates[1:]:
            current = self._intersect_sorted(current, other)
            if not current:
                break

        return self._to_windows(current)

    @staticmethod
    def _intersect_sorted(first: Iterable[int], second: Iterable[int]) -> List[int]:
        result: List[int] = []
        iter_a = iter(first)
        iter_b = iter(second)
        try:
            a = next(iter_a)
            b = next(iter_b)
            while True:
                if a == b:
                    result.append(a)
                    a = next(iter_a)
                    b = next(iter_b)
                elif a < b:
                    a = next(iter_a)
                else:
                    b = next(iter_b)
        except StopIteration:
            return result

    @staticmethod
    def _to_windows(indices: Iterable[int]) -> List[Tuple[int, int]]:
        windows: List[Tuple[int, int]] = []
        iterator = iter(indices)
        try:
            start = prev = next(iterator)
        except StopIteration:
            return windows
        for index in iterator:
            if index == prev + 1:
                prev = index
                continue
            windows.append((start, prev + 1))
            start = prev = index
        windows.append((start, prev + 1))
        return windows

    @property
    def last_count(self) -> int:
        """Return the size of the most recent filtered result set."""

        return self._last_count

    def _filters_key(self, filters: Mapping[str, object]) -> Tuple[str, str, bool]:
        return (
            self._prepare_key(filters.get("group_code")),
            self._prepare_key(filters.get("reg_center")),
            bool(filters.get("selected_only")),
        )

    def _add_selected_index(self, index: int) -> None:
        position = bisect_left(self._selected_indices, index)
        if position >= len(self._selected_indices) or self._selected_indices[position] != index:
            self._selected_indices.insert(position, index)

    def _remove_selected_index(self, index: int) -> None:
        position = bisect_left(self._selected_indices, index)
        if position < len(self._selected_indices) and self._selected_indices[position] == index:
            self._selected_indices.pop(position)


__all__ = ["TraceFilterIndex", "TraceStorageProtocol"]

