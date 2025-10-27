"""Strict scoring reporter validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sma.ci_hardening.strict_reporter import (
    PytestSummary,
    StrictScoringError,
    enforce_caps,
    load_summary,
    parse_summary,
)


def test_summary_caps() -> None:
    """Warnings and skips should register appropriate caps."""

    summary = PytestSummary(passed=5, failed=0, xfailed=1, skipped=1, warnings=2)
    caps = enforce_caps(summary)
    assert caps["warnings"] == 90
    assert caps["skip_xfail"] == 92


def test_parse_summary_invalid() -> None:
    """Invalid summary formats must raise deterministic errors."""

    with pytest.raises(StrictScoringError):
        parse_summary("not a summary")


def test_load_summary(tmp_path: Path) -> None:
    """Loading from disk should parse valid summaries."""

    path = tmp_path / "pytest-summary.txt"
    path.write_text(
        "= 3 passed, 0 failed, 0 xfailed, 0 skipped, 0 warnings", encoding="utf-8"
    )
    summary = load_summary(path)
    assert summary.passed == 3
