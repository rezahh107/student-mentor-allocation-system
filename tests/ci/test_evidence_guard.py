from __future__ import annotations

import pytest

import strict_report


def test_missing_agents_sections_raise_deterministic_error() -> None:
    minimal = {
        "AGENTS.md::6) Observability & Security — Auth & Metrics": (
            "tests/obs/test_auth_and_audit_metrics.py::test_auth_and_audit_metrics",
        )
    }
    with pytest.raises(SystemExit) as excinfo:
        strict_report.ensure_required_agents_sections(minimal)
    assert str(excinfo.value) == strict_report.PERSIAN_EVIDENCE_SECTION_MISSING

