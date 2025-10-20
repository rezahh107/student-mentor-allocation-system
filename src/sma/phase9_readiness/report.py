from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Sequence


_SUMMARY_PATTERN = re.compile(
    r"=+\s*(?P<passed>\d+) passed,\s*(?P<failed>\d+) failed,\s*(?P<xfailed>\d+) xfailed,\s*(?P<skipped>\d+) skipped(?:,\s*(?P<warnings>\d+) warnings)?"
)

PHASE9_SPEC_KEYS: tuple[str, ...] = (
    "uat_plan",
    "pilot",
    "bluegreen",
    "backup",
    "retention",
    "metrics_guard",
)

DEFAULT_INTEGRATION_HINTS: tuple[str, ...] = (
    "tests/phase9_readiness/",
    "tests/pilot/",
    "tests/retention/",
    "tests/deploy/",
    "tests/backup/",
    "tests/security/",
)


@dataclass(frozen=True)
class PytestSummary:
    passed: int
    failed: int
    xfailed: int
    skipped: int
    warnings: int


def parse_pytest_summary(output: str) -> PytestSummary:
    match = _SUMMARY_PATTERN.search(output)
    if not match:
        raise ValueError("خلاصه pytest پیدا نشد.")
    values = {key: int(value or 0) for key, value in match.groupdict(default="0").items()}
    return PytestSummary(**values)


def apply_gui_reallocation(axes: Mapping[str, float], *, gui_in_scope: bool) -> tuple[Dict[str, float], str]:
    result = dict(axes)
    if gui_in_scope:
        return result, "GUI در محدوده است؛ امتیازها تغییری نکرد."
    perf = float(result.get("performance", 40.0)) + 9.0
    excel = float(result.get("excel", 40.0)) + 6.0
    result.update({
        "performance": min(perf, 49.0),
        "excel": min(excel, 46.0),
        "gui": 0.0,
    })
    return result, "GUI خارج از محدوده بود؛ +۹ امتیاز به عملکرد و +۶ امتیاز به اکسل منتقل شد."


def assert_zero_warnings(summary: PytestSummary) -> None:
    if summary.warnings:
        raise AssertionError(f"هشدار pytest یافت شد: {summary.warnings}")


def assert_no_unjustified_skips(summary: PytestSummary) -> None:
    if summary.skipped or summary.xfailed:
        raise AssertionError(
            f"تست‌های پرش‌خورده بدون توجیه: skipped={summary.skipped} xfailed={summary.xfailed}"
        )


def ensure_evidence_quota(
    evidence: Mapping[str, Sequence[str]],
    *,
    integration_hints: Sequence[str] = DEFAULT_INTEGRATION_HINTS,
) -> None:
    missing = [key for key in PHASE9_SPEC_KEYS if not evidence.get(key)]
    if missing:
        raise AssertionError(f"شواهد ناقص برای مشخصات: {', '.join(sorted(missing))}")
    integration_total = 0
    for values in evidence.values():
        for value in values:
            text = str(value)
            if any(hint in text for hint in integration_hints):
                integration_total += 1
    if integration_total < 3:
        raise AssertionError("حداقل سه شاهد از تست‌های یکپارچه لازم است.")


__all__ = [
    "parse_pytest_summary",
    "apply_gui_reallocation",
    "PytestSummary",
    "assert_zero_warnings",
    "assert_no_unjustified_skips",
    "ensure_evidence_quota",
    "PHASE9_SPEC_KEYS",
    "DEFAULT_INTEGRATION_HINTS",
]
