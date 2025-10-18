from __future__ import annotations

import os
import tracemalloc
from typing import Iterator

import csv

from phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic
from phase6_import_to_sabt.sanitization import sanitize_text


_DEFAULT_STRESS_ROWS = 12_000
_MINIMUM_STRESS_ROWS = 3


def _resolve_total_rows() -> int:
    raw_value = os.getenv("EXPORT_STRESS_ROWS")
    if raw_value is None:
        return _DEFAULT_STRESS_ROWS
    candidate_text = sanitize_text(raw_value)
    try:
        candidate = int(candidate_text or 0)
    except (TypeError, ValueError):
        return _DEFAULT_STRESS_ROWS
    if candidate <= 0:
        return _DEFAULT_STRESS_ROWS
    return max(candidate, _MINIMUM_STRESS_ROWS)


def _build_row(index: int) -> dict[str, object]:
    very_long = "ی" * 4096 + "ك" * 2048
    row = {
        "national_id": f"{index:010d}",
        "first_name": f"نام{index}\u200c",  # zero-width joiner
        "last_name": f"خانواده{index}",
        "mobile": "۰۹١٢٣٤٥٦٧٨٩",  # mixed Persian/Arabic digits
        "notes": f" مقدار {index} ",
    }
    if index == 0:
        row["notes"] = "=SUM(A1:A2)"
    elif index == 1:
        row["notes"] = very_long
    if index in {2, 5000} or (index > 0 and index % 5000 == 0):
        row["last_name"] = None
    return row


def test_huge_export_streaming_memory_bound_parametrized(cleanup_fixtures) -> None:  # type: ignore[no-untyped-def]
    cleanup_fixtures.flush_state()
    header = ["national_id", "first_name", "last_name", "mobile", "notes"]
    destination = cleanup_fixtures.base_dir / "storage" / "exports" / "huge.csv"
    total_rows = _resolve_total_rows()

    def _row_iter() -> Iterator[dict[str, object]]:
        for index in range(total_rows):
            yield _build_row(index)

    tracemalloc.start()
    write_csv_atomic(
        destination,
        _row_iter(),
        header=header,
        sensitive_fields=("national_id", "mobile"),
        newline="\r\n",
        fsync=True,
    )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert destination.exists(), cleanup_fixtures.context(path=str(destination))

    with destination.open("rb") as handle:
        sample = handle.read(4096)
    assert sample.startswith(b"\xef\xbb\xbf"), cleanup_fixtures.context(prefix=sample[:4])
    assert b"\r\n" in sample, cleanup_fixtures.context(sample=sample[:32])

    with destination.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header_row = [cell.replace('"', '').lstrip("\ufeff") for cell in next(reader)]
        assert header_row == header, cleanup_fixtures.context(header_row=header_row)
        first_row = next(reader)
        assert first_row[0].startswith("000"), cleanup_fixtures.context(first_row=first_row)
        assert first_row[-1].startswith("'"), cleanup_fixtures.context(first_row=first_row)
        row_count = 1
        last_row = first_row
        for row in reader:
            row_count += 1
            last_row = row
        assert row_count == total_rows, cleanup_fixtures.context(row_count=row_count, total_rows=total_rows)
        last_identifier = last_row[0].strip("'\"") if last_row else "0"
        assert int(last_identifier) == total_rows - 1, cleanup_fixtures.context(last_row=last_row)

    assert peak <= 300 * 1024 * 1024, {
        **cleanup_fixtures.context(peak_bytes=peak, current_bytes=current),
        "rows": total_rows,
        "file": str(destination),
    }

