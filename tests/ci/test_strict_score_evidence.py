from __future__ import annotations

from collections import Counter

from ops.evidence import PHASE6_SPEC_ITEMS

REQUIRED_ITEMS = {
    "dashboards_json",
    "ssr_ops_pages",
    "rbac_scope",
    "replica_adapter",
    "metrics_token_guard",
    "alerts_mapping",
    "middleware_order",
    "deterministic_clock",
    "config_guard",
    "ui_states",
    "perf_budget",
    "dashboard_smoke",
    "warnings_gate",
    "evidence_quota",
    "excel_formula_guard",
}


def _is_integration_test(reference: str) -> bool:
    return reference.startswith("tests::") and any(
        marker in reference
        for marker in (
            "tests/rbac/",
            "tests/ui/",
            "tests/dbreplica/",
            "tests/obs/",
            "tests/perf/",
            "tests/security/",
            "tests/docs/",
            "tests/export/",
        )
    )


def test_all_spec_items_have_evidence():
    missing_items = REQUIRED_ITEMS - PHASE6_SPEC_ITEMS.keys()
    assert not missing_items, f"Missing spec evidence entries: {sorted(missing_items)}"

    empty_items = [key for key, value in PHASE6_SPEC_ITEMS.items() if not value]
    assert not empty_items, f"Spec items without evidence: {empty_items}"

    malformed = [
        (key, evidence)
        for key, evidences in PHASE6_SPEC_ITEMS.items()
        for evidence in evidences
        if "::" not in evidence
    ]
    assert not malformed, f"Malformed evidence entries: {malformed}"

    integration_refs = {
        evidence
        for evidences in PHASE6_SPEC_ITEMS.values()
        for evidence in evidences
        if _is_integration_test(evidence)
    }
    assert len(integration_refs) >= 3, f"Need >=3 integration evidences, have {len(integration_refs)}"

    duplicates = [item for item, count in Counter(integration_refs).items() if count > 1]
    assert not duplicates, f"Duplicate evidence references detected: {duplicates}"

    unexpected = [key for key in PHASE6_SPEC_ITEMS if key not in REQUIRED_ITEMS]
    assert not unexpected, f"Unexpected spec entries present: {unexpected}"
