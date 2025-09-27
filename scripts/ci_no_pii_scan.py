#!/usr/bin/env python3
"""Lightweight scanner ensuring logs/artifacts do not leak raw PII."""
from __future__ import annotations

import argparse
import fnmatch
import re
from pathlib import Path
from typing import Iterable, Iterator, Sequence

DIGIT_TRANSLATION = str.maketrans(
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
MOBILE_RE = re.compile(r"(?<!\d)(09\d{9})(?!\d)")
NATIONAL_ID_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")
MASKED_RE = re.compile(r"0{2,}|\*{2,}|#\*{2,}|٠{2,}|۰{2,}")
MAX_BYTES = 1_048_576


class ScanError(RuntimeError):
    """Raised when inputs for the scan cannot be processed."""


def _expand_globs(patterns: Sequence[str]) -> list[Path]:
    matched: list[Path] = []
    for pattern in patterns:
        for resolved in Path().glob(pattern):
            if resolved.is_file():
                matched.append(resolved)
            elif resolved.is_dir():
                matched.extend(candidate for candidate in resolved.rglob("*") if candidate.is_file())
    return matched


def _iter_paths(entries: Iterable[str], *, include: Sequence[str], exclude: Sequence[str]) -> Iterator[Path]:
    include_paths = set(_expand_globs(include)) if include else set()
    if include_paths:
        candidates = include_paths
    else:
        candidates = set()
        for entry in entries:
            path = Path(entry)
            if not path.exists():
                continue
            if path.is_file():
                candidates.add(path)
            else:
                candidates.update(candidate for candidate in path.rglob("*") if candidate.is_file())

    for candidate in sorted(candidates):
        if any(fnmatch.fnmatch(candidate.as_posix(), pattern) for pattern in exclude):
            continue
        yield candidate


def _mask(value: str) -> str:
    if len(value) <= 4:
        return value
    return value[:3] + "****" + value[-2:]


def _scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except UnicodeDecodeError:  # pragma: no cover - defensive
        return []
    if len(text) > MAX_BYTES:
        text = text[-MAX_BYTES:]
    normalized = text.translate(DIGIT_TRANSLATION)
    findings: list[str] = []
    for pattern, label in ((MOBILE_RE, "شماره موبایل"), (NATIONAL_ID_RE, "کد ملی")):
        for match in pattern.finditer(normalized):
            value = match.group(1)
            if MASKED_RE.search(value):
                continue
            findings.append(f"{label}:{_mask(value)}")
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description="PII leak scanner")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["reports", "artifacts"],
        help="مسیرهایی که باید بررسی شوند",
    )
    parser.add_argument(
        "--include-glob",
        action="append",
        default=[],
        help="الگوی glob برای افزودن فایل‌ها (می‌تواند تکرار شود)",
    )
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="الگوی glob برای نادیده‌گرفتن فایل‌ها",
    )
    args = parser.parse_args()

    try:
        findings: list[str] = []
        for candidate in _iter_paths(args.paths, include=args.include_glob, exclude=args.exclude_glob):
            findings.extend(_scan_file(candidate))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"⚠️ خطای غیرمنتظره در اسکن محرمانگی: {exc}")
        raise SystemExit(2) from exc

    if findings:
        joined = "; ".join(findings)
        print(f"❌ دادهٔ حساس بدون ماسک کشف شد: {joined}")
        raise SystemExit(1)

    print("✅ هیچ نشانه‌ای از دادهٔ حساس غیرماسک‌شده یافت نشد.")


if __name__ == "__main__":
    main()
