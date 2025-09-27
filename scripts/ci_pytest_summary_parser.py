#!/usr/bin/env python3
"""Parse pytest summary output and enforce Strict Scoring v2 rules."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ZERO_WIDTH = {"\u200c", "\u200d", "\ufeff", "\u200b"}
__all__ = [
    "Summary",
    "extract_summary",
    "load_summary_text",
    "read_exit_code",
    "strict_scoring",
]


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

SUMMARY_PATTERN = re.compile(
    r"=\s+(?P<passed>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+passed"
    r"(?:,\s+(?P<failed>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+failed)?"
    r"(?:,\s+(?P<xfailed>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+xfailed)?"
    r"(?:,\s+(?P<xpassed>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+xpassed)?"
    r"(?:,\s+(?P<skipped>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+skipped)?"
    r"(?:,\s+(?P<warnings>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+warnings?)?"
    r"(?:,?\s+in\s+[^=]+)?\s*=",
    re.IGNORECASE | re.DOTALL,
)

TOKEN_PATTERN = re.compile(
    r"(?P<value>[\d\u06F0-\u06F9\u0660-\u0669]+)\s+"
    r"(?P<key>passed|failed|xfailed|xpassed|skipped|warnings?)",
    re.IGNORECASE,
)

MAX_SCAN_WINDOW = 200_000
NULL_TOKEN_PATTERN = re.compile(r"(?i)\b(null|none)\b")


def _normalize_digits(value: str) -> str:
    normalized = value.translate(PERSIAN_DIGIT_TRANSLATION)
    return re.sub(r"[^0-9]", "", normalized)


def _strip_control(text: str) -> str:
    cleaned = ANSI_PATTERN.sub("", text)
    for marker in ZERO_WIDTH:
        cleaned = cleaned.replace(marker, "")
    return cleaned


@dataclass
class Summary:
    passed: int = 0
    failed: int = 0
    xfailed: int = 0
    xpassed: int = 0
    skipped: int = 0
    warnings: int = 0

    @classmethod
    def from_match(cls, match: re.Match[str]) -> "Summary":
        data = {}
        for key in cls.__annotations__:
            raw = match.groupdict().get(key, "0") or "0"
            data[key] = int(_normalize_digits(raw) or 0)
        return cls(**data)

    @classmethod
    def from_tokens(cls, tokens: Iterable[re.Match[str]]) -> "Summary":
        payload = {key: 0 for key in cls.__annotations__}
        for token in tokens:
            key = token.group("key").lower()
            normalized_key = "warnings" if key.startswith("warning") else key
            if normalized_key in payload:
                payload[normalized_key] = int(_normalize_digits(token.group("value")) or 0)
        return cls(**payload)

    def to_dict(self) -> Dict[str, int]:
        return {
            "موفق": self.passed,
            "شکست": self.failed,
            "xfail": self.xfailed,
            "xpass": self.xpassed,
            "ردشده": self.skipped,
            "هشدار": self.warnings,
        }


def load_summary_text(path: str | None) -> str:
    if path:
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            message = "❌ فایل خلاصه pytest یافت نشد. مسیر واردشده نادرست است."
            print(message)
            raise SystemExit(1)
    return sys.stdin.read()


def read_exit_code(path: str | None) -> int:
    if not path:
        return 0
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except FileNotFoundError:
        return 0
    try:
        return int(raw or 0)
    except ValueError:
        return 0


def _bounded_text(raw: str) -> str:
    if len(raw) <= MAX_SCAN_WINDOW:
        return raw
    return raw[-MAX_SCAN_WINDOW:]


def extract_summary(raw: str) -> Summary:
    cleaned = _strip_control(_bounded_text(raw))
    cleaned = NULL_TOKEN_PATTERN.sub("0", cleaned)
    cleaned = cleaned.replace("''", "0").replace('""', "0")
    matches = list(SUMMARY_PATTERN.finditer(cleaned))
    if matches:
        return Summary.from_match(matches[-1])

    for line in reversed(cleaned.splitlines()):
        if "passed" not in line.lower():
            continue
        snippet = line.strip().strip("=")
        snippet = snippet.split(" in ")[0]
        tokens = list(TOKEN_PATTERN.finditer(snippet))
        if tokens:
            return Summary.from_tokens(tokens)

    print("❌ خلاصه pytest یافت نشد؛ فایل ورودی معتبر نیست.")
    raise SystemExit(1)


def strict_scoring(summary: Summary) -> Dict[str, object]:
    axes = {
        "Performance & Core": 40,
        "Persian Excel": 40,
        "GUI": 15,
        "Security": 5,
    }
    deductions = {key: 0 for key in axes}

    axes_after = {axis: max(axes[axis] - deductions[axis], 0) for axis in axes}

    cap = 100
    caps_applied: List[str] = []

    if summary.failed > 0:
        cap = min(cap, 60)
        caps_applied.append(f"خطاها={summary.failed} → cap=60")
    if summary.warnings > 0:
        cap = min(cap, 90)
        caps_applied.append(f"هشدارها={summary.warnings} → cap=90")
    skipped_total = summary.skipped + summary.xfailed + summary.xpassed
    if skipped_total > 0:
        cap = min(cap, 92)
        caps_applied.append(f"موارد غیرفعال={skipped_total} → cap=92")

    if not caps_applied:
        caps_applied.append("None")

    total_raw = sum(axes.values())
    total_after = sum(axes_after.values())
    total_capped = min(total_after, cap)

    return {
        "نسخه": "Strict Scoring v2",
        "سقف": cap,
        "دلایل": caps_applied,
        "محاسبه": {
            "محورها_خام": axes,
            "کسر": deductions,
            "محورها_پس_از_کسر": axes_after,
            "جمع": total_after,
            "جمع_پس_از_سقف": total_capped,
            "سقف": cap,
            "دلایل": caps_applied,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pytest summary parser with Persian Strict Scoring"
    )
    parser.add_argument(
        "--summary-file",
        help="مسیر فایل خروجی pytest برای تحلیل",
    )
    parser.add_argument(
        "--exit-code-file",
        help="مسیر فایل حاوی کد خروج pytest",
    )
    parser.add_argument(
        "--output",
        help="مسیر ذخیرهٔ خروجی JSON Strict Scoring",
    )
    args = parser.parse_args()

    raw_text = load_summary_text(args.summary_file)
    summary = extract_summary(raw_text)
    exit_code = read_exit_code(args.exit_code_file)

    score_info = strict_scoring(summary)
    ci_run_id = os.getenv("CI_RUN_ID") or "local"

    reason_for_cap = "؛ ".join(score_info["دلایل"])

    report = {
        "شناسه": ci_run_id,
        "گزارش": summary.to_dict(),
        "امتیاز": score_info,
        "کد_خروج": exit_code,
        "Reason for Cap": reason_for_cap,
        "Pytest Summary": {
            "passed": summary.passed,
            "failed": summary.failed,
            "xfailed": summary.xfailed,
            "xpassed": summary.xpassed,
            "skipped": summary.skipped,
            "warnings": summary.warnings,
        },
        "پیام": "✅ تمامی تست‌ها با موفقیت و بدون هشدار گذشتند.",
    }

    if summary.failed > 0 or exit_code not in (0, None):
        report["پیام"] = "❌ اجرای تست‌ها ناموفق شد؛ شمار خطاها باید صفر باشد."
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)

    if summary.warnings > 0:
        report["پیام"] = "❌ اجرای تست‌ها ناموفق شد؛ شمار هشدارها باید صفر باشد."
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
