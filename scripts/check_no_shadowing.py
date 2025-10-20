#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import tracemalloc
from typing import Iterable

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CRITICAL_NAMES = {
    "fastapi",
    "sqlalchemy",
    "pytest",
    "pydantic",
    "requests",
    "numpy",
    "pandas",
    "uvicorn",
    "redis",
    "fakeredis",
}

PYTHONPATH_PATTERN = re.compile(r"PYTHONPATH\s*=\s*(['\"]?)(?P<value>[^'\"\n]+)\1")

SCAN_EXTENSIONS = {".sh", ".py", ".ps1", ".md", ".txt", ".yml", ".yaml"}


def _iter_files(root: pathlib.Path) -> Iterable[pathlib.Path]:
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.suffix not in SCAN_EXTENSIONS:
            continue
        yield path


def scan_repository(repo_root: pathlib.Path) -> tuple[list[str], dict[str, float | int]]:
    start = time.perf_counter()
    tracemalloc.start()

    violations: list[str] = []
    scanned_count = 0

    for critical in sorted(CRITICAL_NAMES):
        candidate = repo_root / "src" / critical
        if candidate.exists():
            violations.append(f"خطا: پوشهٔ محلی همنام با کتابخانهٔ ثالث یافت شد: {critical}")

    for path in _iter_files(repo_root):
        scanned_count += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in PYTHONPATH_PATTERN.finditer(text):
            value = match.group("value")
            segments = [segment.strip() for segment in value.split(":" ) if segment.strip()]
            if not segments:
                continue
            first_segment = segments[0]
            normalized = first_segment.replace("$PWD", "").replace("%CD%", "").strip("/\\")
            if normalized.startswith("src") or normalized == "src":
                violations.append(
                    f"خطا: قانون ایمپورت نقض شد؛ فقط از sma.* برای کد first-party استفاده کنید. ({path})"
                )
                break

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    duration_seconds = time.perf_counter() - start

    telemetry = {
        "duration_seconds": duration_seconds,
        "peak_bytes": peak_bytes,
        "scanned_files": scanned_count,
    }
    return violations, telemetry


def main() -> int:
    repo_root = REPO_ROOT
    violations, telemetry = scan_repository(repo_root)
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(json.dumps(telemetry, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1

    print("بازبینی سایه‌زنی بسته‌ها بدون مشکل بود.")
    print(json.dumps(telemetry, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["scan_repository", "main"]
