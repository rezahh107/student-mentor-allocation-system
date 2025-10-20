from __future__ import annotations

import pytest

from sma.phase9_readiness.report import DEFAULT_INTEGRATION_HINTS, ensure_evidence_quota


def build_evidence_map() -> dict[str, list[str]]:
    return {
        "uat_plan": ["tests/phase9_readiness/test_traceability.py::test_traceability_matrix_complete"],
        "pilot": ["tests/pilot/test_pilot_streaming_meter.py::test_streaming_no_buffer_blowup"],
        "bluegreen": ["tests/phase9_readiness/test_bluegreen.py::test_blue_green_no_downtime"],
        "backup": ["tests/phase9_readiness/test_backup.py::test_restore_with_hash_verify"],
        "retention": ["tests/retention/test_retention_policy_check.py::test_retention_fs_timestamp_validation"],
        "metrics_guard": ["tests/phase9_readiness/test_metrics_guard.py::test_metrics_token_guard_persists"],
    }


def test_evidence_quota_enforced() -> None:
    evidence = build_evidence_map()
    ensure_evidence_quota(evidence, integration_hints=DEFAULT_INTEGRATION_HINTS)


def test_missing_evidence_raises() -> None:
    evidence = build_evidence_map()
    evidence["pilot"] = []
    with pytest.raises(AssertionError):
        ensure_evidence_quota(evidence, integration_hints=DEFAULT_INTEGRATION_HINTS)


def test_integration_quota_requires_three() -> None:
    evidence = build_evidence_map()
    for key in evidence:
        evidence[key] = [f"docs/{key}.md"]
    evidence["uat_plan"] = ["tests/phase9_readiness/test_traceability.py::test_traceability_matrix_complete"]
    evidence["pilot"] = ["tests/pilot/test_pilot_streaming_meter.py::test_streaming_no_buffer_blowup"]
    with pytest.raises(AssertionError):
        ensure_evidence_quota(evidence, integration_hints=DEFAULT_INTEGRATION_HINTS)
