from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence, Tuple

from phase6_import_to_sabt.exceptions import ExportIOError, ExportValidationError
from phase6_import_to_sabt.metrics import ExporterMetrics
from phase6_import_to_sabt.sanitization import sanitize_text

INVALID_SORT_KEY_MESSAGE = "کلید مرتب‌سازی نامعتبر است."
SPILL_WRITE_ERROR_MESSAGE = "نوشتن فایل موقت ناموفق بود؛ لطفاً دوباره تلاش کنید."


@dataclass(slots=True)
class SortPlan:
    chunk_paths: list[Path]
    in_memory: list[tuple[Tuple[str, ...], dict[str, str]]]
    total_rows: int
    chunk_count: int
    spill_bytes: int
    format_label: str


@dataclass(order=True)
class _HeapItem:
    key: Tuple[str, ...]
    index: int
    row: dict[str, str] = field(compare=False)
    iterator: Iterator[tuple[Tuple[str, ...], dict[str, str]]] = field(compare=False)


class ExternalSorter:
    """External sorter that spills sorted chunks to disk and merges lazily."""

    def __init__(
        self,
        *,
        sort_keys: Sequence[str],
        buffer_rows: int = 20_000,
        workspace_root: Path,
        correlation_id: str,
        metrics: ExporterMetrics | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if buffer_rows <= 0:
            raise ValueError("buffer_rows must be positive")
        if len(sort_keys) == 0:
            raise ValueError("sort_keys must not be empty")
        self._sort_keys = tuple(sort_keys)
        self._buffer_rows = buffer_rows
        self._metrics = metrics
        self._logger = logger or logging.getLogger(__name__)
        self._correlation_id = correlation_id
        self._workspace_root = workspace_root
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        self._workspace = Path(
            tempfile.mkdtemp(prefix=f"{correlation_id}_", dir=str(self._workspace_root))
        )
        self._current_format: str | None = None

    def prepare(
        self,
        rows: Iterable[dict[str, str]],
        *,
        format_label: str,
    ) -> SortPlan:
        self._current_format = format_label
        chunk_paths: list[Path] = []
        buffer: list[tuple[Tuple[str, ...], dict[str, str]]] = []
        total_rows = 0
        spill_bytes = 0
        for row in rows:
            normalized = self._normalize_row(row)
            key = self._build_key(normalized)
            buffer.append((key, normalized))
            total_rows += 1
            if len(buffer) >= self._buffer_rows:
                path, written = self._spill_chunk(buffer, index=len(chunk_paths))
                chunk_paths.append(path)
                spill_bytes += written
                buffer.clear()
        in_memory: list[tuple[Tuple[str, ...], dict[str, str]]] = []
        if chunk_paths:
            buffer.sort(key=lambda item: item[0])
            in_memory.extend(buffer)
        else:
            buffer.sort(key=lambda item: item[0])
            in_memory = buffer
        plan = SortPlan(
            chunk_paths=chunk_paths,
            in_memory=in_memory,
            total_rows=total_rows,
            chunk_count=len(chunk_paths),
            spill_bytes=spill_bytes,
            format_label=format_label,
        )
        if self._metrics and total_rows:
            self._metrics.observe_sort_rows(format_label=format_label, rows=total_rows)
        return plan

    def iter_sorted(self, plan: SortPlan) -> Iterator[dict[str, str]]:
        if plan.chunk_count == 0:
            for _, row in plan.in_memory:
                yield row
            return

        def _generator() -> Iterator[dict[str, str]]:
            iterators: list[Iterator[tuple[Tuple[str, ...], dict[str, str]]]] = [
                self._chunk_iterator(path) for path in plan.chunk_paths
            ]
            if plan.in_memory:
                iterators.append(self._memory_iterator(plan.in_memory))
            if self._metrics:
                self._metrics.observe_sort_merge(format_label=plan.format_label)
            heap: list[_HeapItem] = []
            for index, iterator in enumerate(iterators):
                try:
                    key, row = next(iterator)
                except StopIteration:
                    continue
                heap.append(_HeapItem(key=key, index=index, row=row, iterator=iterator))
            import heapq

            heapq.heapify(heap)
            while heap:
                item = heapq.heappop(heap)
                yield item.row
                try:
                    next_key, next_row = next(item.iterator)
                except StopIteration:
                    continue
                heapq.heappush(
                    heap,
                    _HeapItem(key=next_key, index=item.index, row=next_row, iterator=item.iterator),
                )

        return _generator()

    def cleanup(self, plan: SortPlan | None) -> None:
        if plan is not None:
            for path in plan.chunk_paths:
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
        self._remove_workspace()
        self._current_format = None

    # internal helpers
    def _normalize_row(self, row: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in row.items():
            if value is None:
                normalized[key] = ""
                continue
            if isinstance(value, str):
                normalized[key] = sanitize_text(value)
            else:
                normalized[key] = sanitize_text(str(value))
        return normalized

    def _build_key(self, row: dict[str, str]) -> Tuple[str, ...]:
        components: list[str] = []
        try:
            for name in self._sort_keys:
                if name == "year_code":
                    components.append(str(row[name]))
                elif name == "reg_center":
                    components.append(f"{self._to_int(row.get(name)):03d}")
                elif name == "group_code":
                    components.append(f"{self._to_int(row.get(name)):06d}")
                elif name == "school_code":
                    components.append(f"{self._to_int(row.get(name), default=999_999):06d}")
                else:
                    components.append(str(row[name]))
        except KeyError as exc:  # pragma: no cover - defensive branch
            raise ExportValidationError(INVALID_SORT_KEY_MESSAGE) from exc
        return tuple(components)

    def _to_int(self, value: str | None, *, default: int = 0) -> int:
        if value is None or value == "":
            return default
        try:
            return int(str(value))
        except (TypeError, ValueError) as exc:
            raise ExportValidationError(INVALID_SORT_KEY_MESSAGE) from exc

    def _spill_chunk(
        self,
        buffer: list[tuple[Tuple[str, ...], dict[str, str]]],
        *,
        index: int,
    ) -> tuple[Path, int]:
        buffer.sort(key=lambda item: item[0])
        chunk_name = f"{self._correlation_id}_{index:05d}.chunk"
        chunk_path = self._workspace / chunk_name
        temp_path = chunk_path.with_suffix(".part")
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                for key, row in buffer:
                    payload = {"key": list(key), "row": row}
                    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, chunk_path)
        except OSError as exc:  # pragma: no cover - defensive path
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise ExportIOError(SPILL_WRITE_ERROR_MESSAGE) from exc
        bytes_written = chunk_path.stat().st_size
        if self._metrics:
            self._metrics.observe_sort_spill(
                format_label=self._current_format or "unknown",
                bytes_written=bytes_written,
            )
        self._logger.info(
            "external_sort_spill correlation_id=%s chunk=%s rows=%d bytes=%d",
            self._correlation_id,
            chunk_path.name,
            len(buffer),
            bytes_written,
        )
        return chunk_path, bytes_written

    def _chunk_iterator(self, path: Path) -> Iterator[tuple[Tuple[str, ...], dict[str, str]]]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    key = tuple(payload["key"])
                    row = {k: sanitize_text(v) for k, v in payload["row"].items()}
                    yield key, row
        except OSError as exc:  # pragma: no cover - defensive path
            raise ExportIOError(SPILL_WRITE_ERROR_MESSAGE) from exc

    def _memory_iterator(
        self,
        entries: list[tuple[Tuple[str, ...], dict[str, str]]],
    ) -> Iterator[tuple[Tuple[str, ...], dict[str, str]]]:
        for key, row in entries:
            yield key, row

    def _remove_workspace(self) -> None:
        try:
            shutil.rmtree(self._workspace, ignore_errors=True)
        except OSError:  # pragma: no cover - ignore cleanup errors
            pass


__all__ = ["ExternalSorter", "SortPlan"]
