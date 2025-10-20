from __future__ import annotations

import csv
import io

from sma.repo_doctor.exporter import guard_formula, normalize_text, fold_persian_digits, stream_csv


def test_formula_guard_and_crlf() -> None:
    assert guard_formula("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert guard_formula("123") == "123"

    text = normalize_text(" كد\u200cملی ")
    assert text == "کدملی"

    digits = fold_persian_digits("۰۹۱۲۳۴۵۶۷۸۹")
    assert digits == "09123456789"

    headers = ["national_id", "full_name"]
    rows = [["=1+2", "علی"], ["۱۲۳", "کریم"]]
    csv_data, metrics = stream_csv(headers, rows)
    assert csv_data.endswith("\r\n")
    reader = csv.reader(io.StringIO(csv_data))
    assert next(reader) == headers
    assert next(reader)[0].startswith("'")
    assert metrics.p95_latency_ms <= 200
    assert metrics.memory_peak_mb <= 300
