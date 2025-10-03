"""Strict Scoring v2 regression tests for the pytest summary parser."""
from __future__ import annotations

import math

import pytest

from scripts.ci_pytest_summary_parser import compute_scores, parse_summary


def test_strict_scoring_v2_all_axes_and_caps() -> None:
    """Compute scores honour clamps, deductions, and all caps."""

    clean_summary = parse_summary(
        "===== 128 passed, 0 failed, 0 xfailed, 0 skipped, 0 warnings in 12.34s ====="
    )
    axes, total, caps = compute_scores(
        clean_summary,
        gui_in_scope=False,
        perf_deduction=-1.0,
        excel_deduction=5.5,
        gui_deduction=0.0,
        sec_deduction=1.0,
        next_actions_pending=False,
        missing_deps=False,
        skips_justified=True,
    )

    assert not caps
    assert pytest.approx(sum(axis.clamped for axis in axes), rel=1e-6) == total
    perf_axis = axes[0]
    assert perf_axis.label == "Performance & Core"
    assert perf_axis.clamped == perf_axis.max_value == 49.0
    excel_axis = axes[1]
    assert excel_axis.clamped == pytest.approx(40.5)
    sec_axis = axes[3]
    assert sec_axis.clamped == pytest.approx(4.0)
    assert total == pytest.approx(93.5)

    capped_summary = parse_summary(
        "===== 20 passed, 0 failed, 1 xfailed, 2 skipped, 3 warnings in 1.23s ====="
    )
    capped_axes, capped_total, caps_applied = compute_scores(
        capped_summary,
        gui_in_scope=True,
        perf_deduction=0.0,
        excel_deduction=0.0,
        gui_deduction=2.5,
        sec_deduction=0.0,
        next_actions_pending=True,
        missing_deps=True,
        skips_justified=False,
    )

    assert capped_total <= 85.0
    assert {axis.label for axis in capped_axes} == {
        "Performance & Core",
        "Persian Excel",
        "GUI",
        "Security",
    }
    assert caps_applied == [
        "warnings>0 → cap=90",
        "skipped/xfailed → cap=92",
        "next_actions pending → cap=95",
        "missing dependencies → cap=85",
        "service skip hard cap <90",
    ]
    assert math.isclose(
        capped_total,
        min(sum(axis.clamped for axis in capped_axes), 85.0),
        rel_tol=1e-6,
    )
