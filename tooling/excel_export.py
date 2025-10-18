from __future__ import annotations

"""Excel-safe CSV exporter with atomic writes and debugging aids."""

import csv
import io
import json
import os
from collections import deque
from pathlib import Path
from typing import Deque, Iterable, List, Mapping, Sequence

from .clock import Clock
from .domain import normalize_text
from .logging_utils import mask_pii
from .metrics import get_export_bytes_counter, get_export_duration_histogram

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _normalise_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return normalize_text(str(value))


def _guard_formula(value: str) -> str:
    if value and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


class AtomicWriter:
    """Context manager that ensures atomic writes via ``.part`` temporary files."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.tmp = target.with_suffix(target.suffix + ".part")

    def __enter__(self) -> io.TextIOWrapper:
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self.file_handle = open(self.tmp, "w", encoding="utf-8", newline="")
        return self.file_handle

    def __exit__(self, exc_type, exc, tb) -> None:
        self.file_handle.flush()
        os.fsync(self.file_handle.fileno())
        self.file_handle.close()
        if exc_type is None:
            os.replace(self.tmp, self.target)
        else:  # pragma: no cover - defensive cleanup
            try:
                os.remove(self.tmp)
            except FileNotFoundError:
                pass


class ExcelSafeCSVExporter:
    """Stream large iterables to Excel-safe CSV files."""

    def __init__(self, clock: Clock | None = None, chunk_size: int = 1000) -> None:
        self.clock = clock or Clock()
        self.chunk_size = chunk_size
        self.duration_hist = get_export_duration_histogram()
        self.byte_counter = get_export_bytes_counter()

    def export(
        self,
        rows: Iterable[Mapping[str, object]],
        columns: Sequence[str],
        path: Path,
        include_bom: bool = False,
    ) -> Path:
        phase = "write"
        start = self.clock.monotonic()
        buffer: list[list[str]] = []
        head_samples: list[list[str]] = []
        tail_samples: Deque[list[str]] = deque(maxlen=5)
        total_bytes = 0
        try:
            with AtomicWriter(path) as handle:
                writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
                if include_bom:
                    handle.write("\ufeff")
                writer.writerow(list(columns))
                for row in rows:
                    serialised = [
                        _guard_formula(_normalise_value(row.get(column)))
                        for column in columns
                    ]
                    if len(head_samples) < 3:
                        head_samples.append(serialised.copy())
                    else:
                        tail_samples.append(serialised.copy())
                    buffer.append(serialised)
                    if len(buffer) >= self.chunk_size:
                        total_bytes += self._flush(writer, buffer)
                        buffer.clear()
                if buffer:
                    total_bytes += self._flush(writer, buffer)
        except Exception as exc:  # pragma: no cover - exercised via tests
            self._dump_debug_artifact(path, head_samples, list(tail_samples), str(exc))
            raise
        elapsed = self.clock.monotonic() - start
        self.duration_hist.labels(phase=phase).observe(elapsed)
        self.byte_counter.labels(format="csv").inc(total_bytes)
        return path

    def _flush(self, writer: csv._writer, buffer: list[list[str]]) -> int:
        size = 0
        for row in buffer:
            writer.writerow(row)
            size += sum(len(cell) for cell in row)
        self.clock.advance(0.00001 * len(buffer))
        return size

    def _dump_debug_artifact(
        self,
        path: Path,
        head: List[List[str]],
        tail: List[List[str]],
        error: str,
    ) -> None:
        debug_path = path.with_suffix(path.suffix + ".debug.json")
        payload = {
            "error": mask_pii(error),
            "chunk_size": self.chunk_size,
            "head": [[mask_pii(cell) for cell in row] for row in head],
            "tail": [[mask_pii(cell) for cell in row] for row in tail],
        }
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
