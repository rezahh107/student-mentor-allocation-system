from __future__ import annotations

import pytest

from src.phase9_readiness.report import PytestSummary, assert_no_unjustified_skips


def test_no_unjustified_skips_passes() -> None:
    summary = PytestSummary(passed=8, failed=0, xfailed=0, skipped=0, warnings=0)
    assert_no_unjustified_skips(summary)


def test_skips_trigger_assertion() -> None:
    summary = PytestSummary(passed=8, failed=0, xfailed=1, skipped=2, warnings=0)
    with pytest.raises(AssertionError):
        assert_no_unjustified_skips(summary)
