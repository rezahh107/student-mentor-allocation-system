from __future__ import annotations

from typing import Dict, List

PHASE6_SPEC_ITEMS: Dict[str, List[str]] = {
    "dashboards_json": [
        "path::ops/dashboards/slo.json",
        "path::ops/dashboards/exports.json",
        "path::ops/dashboards/uploads.json",
        "path::ops/dashboards/errors.json",
        "tests::tests/ops/test_dashboards_json_schema.py::test_dashboards_json_schema_ok",
    ],
    "ssr_ops_pages": [
        "path::src/web/templates/ops_home.html",
        "path::src/web/templates/ops_exports.html",
        "path::src/web/templates/ops_uploads.html",
        "path::src/web/templates/ops_slo.html",
        "tests::tests/ui/test_ops_pages.py::test_ops_pages_render_rtl_no_pii",
    ],
    "rbac_scope": [
        "tests::tests/rbac/test_ops_scope.py::test_manager_sees_only_own_center",
        "tests::tests/rbac/test_ops_scope.py::test_admin_sees_all",
    ],
    "replica_adapter": [
        "path::src/ops/replica_adapter.py",
        "tests::tests/dbreplica/test_readonly_adapter.py::test_replica_timeout_persian_error",
    ],
    "metrics_token_guard": [
        "tests::tests/security/test_metrics_token_guard.py::test_metrics_endpoint_is_public",
        "tests::tests/obs/test_metrics_labels.py::test_expected_metrics_present",
    ],
    "alerts_mapping": [
        "path::docs/ops_metrics_map.md",
        "tests::tests/docs/test_ops_metrics_map.py::test_links_exist",
    ],
    "middleware_order": [
        "tests::tests/mw/test_middleware_order.py::test_order_enforced",
    ],
    "deterministic_clock": [
        "tests::tests/time/test_clock_injection.py::test_injected_clock_used",
    ],
    "config_guard": [
        "tests::tests/config/test_config_guard.py::test_forbid_unknown_keys",
    ],
    "ui_states": [
        "tests::tests/ui/test_ops_states.py::test_empty_and_error_states",
    ],
    "perf_budget": [
        "tests::tests/perf/test_ops_p95.py::test_health_readyz_p95_lt_200ms",
        "tests::tests/perf/test_ops_p95.py::test_ops_pages_p95_lt_400ms",
        "tests::tests/perf/test_memory_budget.py::test_process_memory_lt_300mb",
    ],
    "dashboard_smoke": [
        "tests::tests/obs/test_dashboards_query_smoke.py::test_slo_panels_resolve_metrics",
        "tests::tests/obs/test_dashboards_query_smoke.py::test_export_panels_resolve_metrics",
    ],
    "warnings_gate": [
        "tests::tests/ci/test_no_warnings_gate.py::test_no_warnings",
    ],
    "evidence_quota": [
        "tests::tests/ci/test_strict_score_evidence.py::test_all_spec_items_have_evidence",
    ],
    "excel_formula_guard": [
        "tests::tests/export/test_excel_safety_regression.py::test_formula_injection_guard",
    ],
}

__all__ = ["PHASE6_SPEC_ITEMS"]
