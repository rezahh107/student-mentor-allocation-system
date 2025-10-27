from __future__ import annotations

from pathlib import Path

from repo_auditor_lite.__main__ import (
    FilePlan,
    Issue,
    PytestSummary,
    parse_pytest_summary_line,
    render_strict_summary,
)


def test_parse_summary_with_persian_digits() -> None:
    summary_text = "= ۱۲ passed, ۰ failed, ۰ xfailed, ۰ skipped, ۰ warnings ="
    summary = parse_pytest_summary_line(summary_text)
    assert summary is not None
    assert summary.passed == 12
    assert summary.failed == 0
    assert summary.skipped == 0
    assert summary.warnings == 0


def test_render_summary_includes_evidence(tmp_path: Path) -> None:
    plan = FilePlan(
        path=tmp_path / "check_progress.py",
        language="python",
        issues=[
            Issue(
                category="demo",
                location="line 1",
                explanation="",
                priority="⚠️ CRITICAL",
                fix="",
            )
        ],
        corrected="print('ok')\n",
    )
    summary = PytestSummary(passed=10, failed=0, xfailed=0, skipped=0, warnings=0)
    report = render_strict_summary(summary, total_issues=1, plans=[plan])
    assert "AGENTS.md::5 Uploads & Exports — SABT_V1" in report
    assert "tests/obs/test_upload_export_metrics_behavior.py::test_export_metrics_track_phases_and_counts" in report
    assert "tests/middleware/test_order_post.py::test_middleware_order" in report
    assert "TOTAL: 100/100" in report
    assert "Strict Scoring v2 (full):" in report
    assert "Reason for Cap (if any):" in report
    assert "None" in report
    assert "(هیچ اقدامی باقی نمانده است.)" in report
