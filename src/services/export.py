"""High-level streaming exporters aligned with AGENTS §8.1 budgets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sma.core.clock import Clock, SupportsNow, ensure_clock  # type: ignore[import-not-found]
from sma.phase6_import_to_sabt.xlsx.metrics import ImportExportMetrics  # type: ignore[import-not-found]
from sma.phase6_import_to_sabt.xlsx.writer import XLSXStreamWriter  # type: ignore[import-not-found]

DEFAULT_CHUNK_SIZE = 50_000


@dataclass(frozen=True, slots=True)
class ExportManifest:
    """Result metadata returned by :func:`export_to_xlsx`."""

    path: Path
    sha256: str
    byte_size: int
    row_count: int
    sheets: tuple[tuple[str, int], ...]
    generated_at: datetime
    excel_safety: dict[str, Any]


def stream_students(students: Iterable[Mapping[str, Any]]) -> Iterator[Mapping[str, Any]]:
    """Yield student rows preserving database order without materialising lists."""

    for row in students:
        yield row


def export_to_xlsx(
    *,
    students: Iterable[Mapping[str, Any]],
    output_path: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    clock: Clock | SupportsNow | Callable[[], datetime] | None = None,
    metrics: ImportExportMetrics | None = None,
    on_retry: Callable[[int], None] | None = None,
    sleeper: Callable[[float], None] | None = None,
    format_label: str = "xlsx",
) -> ExportManifest:
    """Stream ``students`` into an XLSX file while obeying atomic write semantics."""

    resolved_clock = ensure_clock(clock, timezone="Asia/Tehran")
    writer = XLSXStreamWriter(chunk_size=chunk_size)
    artifact = writer.write(
        students,
        output_path=output_path,
        on_retry=on_retry,
        metrics=metrics,
        format_label=format_label,
        sleeper=sleeper,
    )
    row_total = sum(artifact.row_counts.values())
    manifest = ExportManifest(
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        row_count=row_total,
        sheets=tuple(sorted(artifact.row_counts.items())),
        generated_at=resolved_clock.now(),
        excel_safety=dict(artifact.excel_safety),
    )
    return manifest


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "ExportManifest",
    "export_to_xlsx",
    "stream_students",
]
