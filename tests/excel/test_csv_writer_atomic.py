from __future__ import annotations

import os
import tracemalloc
from pathlib import Path

import pytest

from phase6_import_to_sabt.exporter.csv_writer import write_csv_atomic
from phase6_import_to_sabt.obs.metrics import build_metrics


@pytest.fixture
def csv_metrics():
    metrics = build_metrics("csv_test")
    yield metrics
    metrics.reset()


def test_csv_writer_formula_guard(tmp_path: Path, csv_metrics):
    destination = tmp_path / "guard.csv"
    rows = [{"name": "=SUM(1,2)", "value": "42"}]
    write_csv_atomic(destination, rows, header=["name", "value"], sensitive_fields=["name"], metrics=csv_metrics)
    content = destination.read_text(encoding="utf-8-sig")
    assert "'=SUM(1,2)" in content


def test_csv_writer_always_quote_sensitive(tmp_path: Path, csv_metrics):
    destination = tmp_path / "quote.csv"
    rows = [{"name": "ali", "national_id": "001234"}]
    write_csv_atomic(destination, rows, header=["name", "national_id"], sensitive_fields=["national_id"], metrics=csv_metrics)
    text = destination.read_text(encoding="utf-8-sig")
    line = text.splitlines()[1]
    assert line.startswith("ali,")
    assert line.endswith('"001234"')


def test_csv_writer_crlf_bom(tmp_path: Path, csv_metrics):
    destination = tmp_path / "linebreak.csv"
    rows = [{"name": "a", "value": "b"}]
    write_csv_atomic(destination, rows, header=["name", "value"], sensitive_fields=["value"], metrics=csv_metrics)
    data = destination.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in data


def test_csv_writer_atomic_rename_fsync(tmp_path: Path, monkeypatch, csv_metrics):
    destination = tmp_path / "atomic.csv"
    fsync_calls: list[int] = []

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    monkeypatch.setattr(os, "fsync", fake_fsync)
    write_csv_atomic(destination, [{"name": "x", "value": "1"}], header=["name", "value"], sensitive_fields=["value"], metrics=csv_metrics)
    assert destination.exists()
    assert not destination.with_suffix(".csv.part").exists()
    assert fsync_calls


def test_streaming_large_rows_bounded_memory(tmp_path: Path, csv_metrics):
    destination = tmp_path / "large.csv"

    def row_generator():
        for i in range(1000):
            yield {"name": f"کاربر {i}", "value": "۷" * 50}

    tracemalloc.start()
    write_csv_atomic(destination, row_generator(), header=["name", "value"], sensitive_fields=["value"], metrics=csv_metrics)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 150 * 1024 * 1024
