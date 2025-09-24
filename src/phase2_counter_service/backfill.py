# -*- coding: utf-8 -*-
"""Streaming CSV backfill implementation for counter assignment."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, cast

from .errors import invalid_gender
from .service import CounterAssignmentService
from .types import BackfillObserver, GenderLiteral
from .validation import COUNTER_PREFIX, ensure_sequence_bounds, ensure_valid_inputs, normalize


@dataclass(slots=True)
class BackfillRow:
    """Normalized CSV row used during streaming backfill."""

    national_id: str
    gender: GenderLiteral
    year_code: str


@dataclass(slots=True)
class BackfillStats:
    """Aggregated statistics returned from :func:`run_backfill`.

    Attributes
    ----------
    total_rows:
        Total number of CSV rows processed.
    applied:
        Number of counters that were generated and persisted.
    reused:
        Number of rows where an existing counter was reused as-is.
    skipped:
        Rows skipped during dry-run capacity planning.
    dry_run:
        ``True`` when the execution ran in dry-run mode.
    prefix_mismatches:
        Count of rows where the stored counter prefix did not match the SSOT expectation.
    """

    total_rows: int
    applied: int
    reused: int
    skipped: int
    dry_run: bool
    prefix_mismatches: int


def _chunked(rows: Iterator[BackfillRow], chunk_size: int) -> Iterator[List[BackfillRow]]:
    """Yield fixed-size chunks from an iterator while keeping memory bounded."""

    chunk: List[BackfillRow] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _parse_rows(csv_path: Path) -> Iterator[BackfillRow]:
    """Stream rows from ``csv_path`` converting them into :class:`BackfillRow`."""

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_no, raw in enumerate(reader, start=2):
            nid_raw = raw.get("national_id", "")
            gender_raw = normalize(raw.get("gender", ""))
            year_raw = raw.get("year_code", "")
            try:
                gender_value = int(gender_raw)
            except ValueError as exc:
                raise invalid_gender(f"مقدار جنسیت نامعتبر در خط {line_no}.") from exc
            typed_gender = cast(GenderLiteral, gender_value)
            nid, year = ensure_valid_inputs(nid_raw, typed_gender, year_raw)
            yield BackfillRow(nid, typed_gender, year)


def run_backfill(
    service: CounterAssignmentService,
    csv_path: Path,
    *,
    chunk_size: int = 500,
    apply: bool = False,
    observer: Optional[BackfillObserver] = None,
) -> BackfillStats:
    """Execute a streaming backfill using ``service`` over ``csv_path``.

    Parameters
    ----------
    service:
        Fully constructed :class:`CounterAssignmentService`.
    csv_path:
        Path to the CSV file containing ``national_id``, ``gender`` and ``year_code`` columns.
    chunk_size:
        Number of rows to process per batch.
    apply:
        When ``True`` the assignments are persisted; otherwise the run is a dry-run.
    observer:
        Optional hook receiving per-chunk statistics, useful for CLI progress output.

    Returns
    -------
    BackfillStats
        Summary of the streaming run including counts for applied, reused and skipped rows.
    """

    rows = _parse_rows(csv_path)
    total_rows = 0
    applied = 0
    reused = 0
    skipped = 0
    prefix_mismatches = 0
    seq_snapshot = dict(service.repository.snapshot_sequences())
    chunk_index = 0

    for chunk in _chunked(rows, chunk_size):
        chunk_index += 1
        total_rows += len(chunk)
        national_ids = [row.national_id for row in chunk]
        existing = service.repository.fetch_existing_counters(national_ids)
        applied_chunk = 0
        reused_chunk = 0
        skipped_chunk = 0
        for row in chunk:
            prefix = COUNTER_PREFIX[row.gender]
            seq_key = (row.year_code, prefix)
            if row.national_id in existing:
                counter_value = existing[row.national_id]
                expected_prefix = f"{row.year_code}{prefix}"
                if not counter_value.startswith(expected_prefix):
                    prefix_mismatches += 1
                    service.logger.warning(
                        "backfill_prefix_mismatch",
                        extra={
                            "شناسه": service.hash_fn(row.national_id),
                            "counter": counter_value,
                            "پیشوند_مورد_انتظار": expected_prefix,
                            "پیشوند_فعلی": counter_value[:5],
                        },
                    )
                reused += 1
                reused_chunk += 1
                continue
            if not apply:
                next_seq = seq_snapshot.get(seq_key, 0) + 1
                ensure_sequence_bounds(next_seq)
                seq_snapshot[seq_key] = next_seq
                skipped += 1
                skipped_chunk += 1
                continue
            counter = service.assign_counter(row.national_id, row.gender, row.year_code)
            seq_snapshot[seq_key] = max(seq_snapshot.get(seq_key, 0), int(counter[-4:]))
            applied += 1
            applied_chunk += 1
        if observer is not None:
            observer.on_chunk(chunk_index, applied_chunk, reused_chunk, skipped_chunk)

    return BackfillStats(
        total_rows=total_rows,
        applied=applied,
        reused=reused,
        skipped=skipped,
        dry_run=not apply,
        prefix_mismatches=prefix_mismatches,
    )
