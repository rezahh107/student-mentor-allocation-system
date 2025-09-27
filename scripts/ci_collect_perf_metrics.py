#!/usr/bin/env python3
"""Collect performance metrics from pytest or time outputs."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PERSIAN_DIGIT_TRANSLATION = str.maketrans(
    {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)

PYTEST_DURATION_RE = re.compile(r"(?P<value>[\d\.,]+)\s*s\s+call", re.IGNORECASE)
TIME_MEMORY_RE = re.compile(r"Maximum resident set size \(kbytes\):\s*(?P<value>[\d\u06F0-\u06F9\u0660-\u0669]+)")


def _normalize_digits(text: str) -> str:
    return text.translate(PERSIAN_DIGIT_TRANSLATION).replace(",", "").strip()


def _read_text(path: Path | None) -> str:
    if not path:
        return ""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _extract_durations(*logs: Path) -> list[float]:
    durations: list[float] = []
    for log in logs:
        text = _read_text(log)
        if not text:
            continue
        for match in PYTEST_DURATION_RE.finditer(text):
            raw_value = _normalize_digits(match.group("value"))
            if not raw_value:
                continue
            try:
                durations.append(float(raw_value))
            except ValueError:
                continue
    return durations


def _extract_memory(*logs: Path) -> list[float]:
    samples: list[float] = []
    for log in logs:
        text = _read_text(log)
        if not text:
            continue
        for match in TIME_MEMORY_RE.finditer(text.translate(PERSIAN_DIGIT_TRANSLATION)):
            raw_value = match.group("value")
            try:
                kb = float(_normalize_digits(raw_value))
            except ValueError:
                continue
            samples.append(kb / 1024.0)
    return samples


def _p95(values: Iterable[float]) -> float:
    ordered = sorted(v for v in values if math.isfinite(v) and v >= 0)
    if not ordered:
        return 0.0
    index = max(int(round(0.95 * len(ordered) + 0.5)) - 1, 0)
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect CI performance metrics")
    parser.add_argument("--pytest-log", action="append", default=[], help="مسیر لاگ pytest برای استخراج زمان")
    parser.add_argument("--time-log", action="append", default=[], help="خروجی /usr/bin/time برای استخراج حافظه")
    parser.add_argument("--output", default="reports/perf.json", help="مسیر ذخیره گزارش JSON")
    args = parser.parse_args()

    duration_logs = [Path(item) for item in args.pytest_log]
    memory_logs = [Path(item) for item in args.time_log]

    durations = _extract_durations(*duration_logs)
    memory = _extract_memory(*memory_logs)

    payload = {
        "clock": "Asia/Tehran",
        "p95_ms": round(_p95(durations) * 1000.0, 3),
        "mem_mb_peak": round(max(memory) if memory else 0.0, 3),
        "samples": len(durations),
        "run_id": os.getenv("CI_RUN_ID", "local"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
