from __future__ import annotations

import pytest

from src.phase9_readiness.report import PytestSummary, assert_zero_warnings


def test_zero_warnings() -> None:
    summary = PytestSummary(passed=12, failed=0, xfailed=0, skipped=0, warnings=0)
    assert_zero_warnings(summary)


def test_warnings_raise_assertion() -> None:
    summary = PytestSummary(passed=10, failed=0, xfailed=0, skipped=0, warnings=2)
    with pytest.raises(AssertionError):
        assert_zero_warnings(summary)
