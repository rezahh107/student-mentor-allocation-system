from __future__ import annotations

import pytest

from src.repo_doctor.report import parse_pytest_summary


def test_parse_pytest_summary() -> None:
    summary = "= 10 passed, 0 failed, 0 xfailed, 0 skipped, 0 warnings in 1.23s"
    result = parse_pytest_summary(summary)
    assert result == {"passed": 10, "failed": 0, "xfailed": 0, "skipped": 0, "warnings": 0}


def test_parse_pytest_summary_missing() -> None:
    with pytest.raises(ValueError):
        parse_pytest_summary("no summary here")
