#!/usr/bin/env python3
"""Strict Scoring v2 parser for pytest summaries."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from typing import Iterable


_SUMMARY_RE = re.compile(
    r"=+\s*(?P<passed>\d+)\s+passed,\s*(?P<failed>\d+)\s+failed,\s*(?P<xfailed>\d+)\s+xfailed,\s*(?P<skipped>\d+)\s+skipped,\s*(?P<warnings>\d+)\s+warnings",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Summary:
    passed: int
    failed: int
    xfailed: int
    skipped: int
    warnings: int


@dataclass(frozen=True)
class AxisScore:
    label: str
    raw: float
    max_value: float

    @property
    def clamped(self) -> float:
        return max(0.0, min(self.raw, self.max_value))


def parse_summary(text: str) -> Summary:
    match = _SUMMARY_RE.search(text)
    if not match:  # pragma: no cover - defensive for CI logs
        raise ValueError("Pytest summary not found in provided text")
    values = {name: int(value) for name, value in match.groupdict().items()}
    return Summary(**values)


def _base_axes(gui_in_scope: bool) -> dict[str, float]:
    if gui_in_scope:
        return {"perf": 40.0, "excel": 40.0, "gui": 15.0, "sec": 5.0}
    # GUI out of scope → redistribute 15 pts as +9 perf / +6 excel
    return {"perf": 49.0, "excel": 46.0, "gui": 0.0, "sec": 5.0}


def compute_scores(
    summary: Summary,
    *,
    gui_in_scope: bool,
    perf_deduction: float,
    excel_deduction: float,
    gui_deduction: float,
    sec_deduction: float,
    next_actions_pending: bool,
    missing_deps: bool,
    skips_justified: bool,
) -> tuple[list[AxisScore], float, list[str]]:
    axes = _base_axes(gui_in_scope)
    raw_axes = [
        AxisScore("Performance & Core", axes["perf"] - perf_deduction, axes["perf"]),
        AxisScore("Persian Excel", axes["excel"] - excel_deduction, axes["excel"]),
        AxisScore("GUI", axes["gui"] - gui_deduction, axes["gui"]),
        AxisScore("Security", axes["sec"] - sec_deduction, axes["sec"]),
    ]

    caps: list[str] = []
    cap_value = 100.0
    if summary.failed:
        caps.append("failures present")
        cap_value = 0.0
    if summary.warnings > 0:
        caps.append("warnings>0 → cap=90")
        cap_value = min(cap_value, 90.0)
    if (summary.skipped + summary.xfailed) > 0 and not skips_justified:
        caps.append("skipped/xfailed → cap=92")
        cap_value = min(cap_value, 92.0)
    if next_actions_pending:
        caps.append("next_actions pending → cap=95")
        cap_value = min(cap_value, 95.0)
    if missing_deps:
        caps.append("missing dependencies → cap=85")
        cap_value = min(cap_value, 85.0)
    if summary.skipped and missing_deps:
        caps.append("service skip hard cap <90")
        cap_value = min(cap_value, 89.9)

    total = sum(axis.clamped for axis in raw_axes)
    total = min(total, cap_value)
    return raw_axes, total, caps


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse pytest summary and compute Strict Scoring v2 totals")
    parser.add_argument("summary", nargs="?", help="Pytest summary string. If omitted, read from stdin.")
    parser.add_argument("--gui-in-scope", action="store_true", help="GUI axis applies (no reallocation)")
    parser.add_argument("--perf-deduction", type=float, default=0.0)
    parser.add_argument("--excel-deduction", type=float, default=0.0)
    parser.add_argument("--gui-deduction", type=float, default=0.0)
    parser.add_argument("--sec-deduction", type=float, default=0.0)
    parser.add_argument("--next-actions", action="store_true", help="Next actions list not empty → cap 95")
    parser.add_argument("--missing-deps", action="store_true", help="Missing dependency fallback encountered")
    parser.add_argument(
        "--skips-justified",
        action="store_true",
        help="Allow documented skips/xfails (disables skip cap)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    summary_text = args.summary or sys.stdin.read()
    summary = parse_summary(summary_text)

    axes, total, caps = compute_scores(
        summary,
        gui_in_scope=args.gui_in_scope,
        perf_deduction=args.perf_deduction,
        excel_deduction=args.excel_deduction,
        gui_deduction=args.gui_deduction,
        sec_deduction=args.sec_deduction,
        next_actions_pending=args.next_actions,
        missing_deps=args.missing_deps,
        skips_justified=args.skips_justified,
    )

    print("Strict Scoring v2")
    print(f"Summary: passed={summary.passed}, failed={summary.failed}, xfailed={summary.xfailed}, skipped={summary.skipped}, warnings={summary.warnings}")
    for axis in axes:
        print(f"{axis.label}: {axis.clamped:.2f}/{axis.max_value:.2f}")
    print(f"TOTAL: {total:.2f}")
    if caps:
        print("Caps applied: " + ", ".join(caps))
    else:
        print("Caps applied: none")

    if summary.failed:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
