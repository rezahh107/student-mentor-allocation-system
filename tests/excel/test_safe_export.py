from __future__ import annotations

import csv
import hashlib
import time
from pathlib import Path
from typing import Callable, Iterable

import pytest
from freezegun import freeze_time

from sma.infrastructure.export.excel_safe import (
    dangerous_prefixes,
    make_excel_safe_writer,
    sanitize_row,
)


@pytest.fixture(autouse=True)
def cleanup_reports(tmp_path: Path):
    """Ensure temporary export artifacts remain isolated per test."""

    namespace = hashlib.blake2s(str(tmp_path).encode("utf-8"), digest_size=6).hexdigest()
    target = tmp_path / f"excel-safe-{namespace}.csv"
    context = {"path": target, "namespace": namespace}
    if target.exists():
        target.unlink()
    try:
        yield context
    finally:
        if target.exists():
            target.unlink()


def run_with_retry(operation: Callable[[], object], *, attempts: int = 3, seed: str = "excel-safe") -> object:
    """Retry helper with deterministic jitter to reduce flakiness under CI."""

    base_delay = 0.04
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"attempt={attempt} error={exc!r}")
            if attempt == attempts:
                raise RuntimeError("; ".join(failures)) from exc
            jitter_seed = hashlib.blake2s(f"{seed}:{attempt}".encode("utf-8"), digest_size=4).hexdigest()
            jitter = (int(jitter_seed, 16) % 10) / 1000.0
            time.sleep(base_delay * attempt + jitter)
    raise RuntimeError("retry helper exhausted without returning")


def _read_rows(path: Path) -> Iterable[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        yield from reader


def _debug_context(sanitized: list[str], namespace: str, path: Path) -> dict[str, object]:
    return {
        "namespace": namespace,
        "sanitized": sanitized,
        "timestamp": time.time(),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
    }


@freeze_time("2024-01-01 00:00:00", tz_offset=3.5)
def test_excel_export_guards_formula_and_utf8(cleanup_reports):
    context = cleanup_reports
    path: Path = context["path"]
    namespace: str = context["namespace"]

    raw_row = [
        "=SUM(A1:A2)",
        "+HACK",
        "-DROP",  # dangerous prefix
        "@CMD",
        "۰۱۲۳۴",  # Persian digits
        "متن‌فارسی\u200cبا اعداد۱۲۳",  # zero-width joiner + mixed digits
        "“quoted text”",
        "safe value",
    ]

    expected_row = run_with_retry(
        lambda: sanitize_row(raw_row, guard_formulas=True),
        seed=f"excel-{namespace}",
    )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = make_excel_safe_writer(handle, guard_formulas=True, quote_all=True)
        writer.writerow(raw_row)

    saved_rows = list(run_with_retry(lambda: list(_read_rows(path)), seed=f"read-{namespace}"))
    assert saved_rows, "No rows were written to the Excel-safe CSV"

    sanitized_row = saved_rows[0]
    debug = _debug_context(sanitized_row, namespace, path)

    assert all(isinstance(cell, str) for cell in sanitized_row), f"Non-str cell detected: {debug}"
    assert sanitized_row == expected_row, (
        "Sanitized row mismatch",
        {"expected": expected_row, "observed": sanitized_row, "debug": debug},
    )

    decoded = path.read_bytes().decode("utf-8")
    assert "۰" not in decoded and "١" not in decoded, f"Persian/Arabic digits leaked: {debug}"
    assert '‌' not in decoded, f"Zero-width characters should be stripped: {debug}"

    for idx, cell in enumerate(sanitized_row):
        if raw_row[idx].startswith(dangerous_prefixes):
            assert cell.startswith("'"), f"Formula guard missing for {raw_row[idx]!r}: {debug}"

    assert decoded.count("'=") >= 1, f"Expected formula guard prefix in output: {debug}"
