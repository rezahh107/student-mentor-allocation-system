from __future__ import annotations

from typing import Dict

from tools.strict_score_core import EvidenceMatrix, ScoreEngine


EVIDENCE_FIXTURE: Dict[str, list[str]] = {
    "state_hygiene": ["tests/obs/test_prom_registry_reset.py::test_registry_fresh_between_tests"],
    "stable_sort_keys": ["tests/exports/test_sabt_core.py::test_stable_sort_order"],
    "chunking_filenames": ["tests/exports/test_sabt_core.py::test_chunking_and_naming_determinism"],
    "excel_safety": ["tests/exports/test_excel_safety_ci.py::test_quotes_formula_guard_crlf_bom"],
    "snapshot_delta": ["tests/exports/test_delta_window.py::test_delta_no_gap_overlap"],
    "atomic_finalize": ["tests/exports/test_manifest.py::test_atomic_manifest_after_files"],
    "counter_year_code": ["tests/counter/test_counter_rules.py::test_regex_and_gender_prefix"],
    "security_access": ["tests/security/test_metrics_and_downloads.py::test_token_and_signed_url"],
    "observability_metrics": ["tests/obs/test_export_metrics.py::test_export_metrics_labels_and_token_guard"],
    "slo_baseline": ["tests/perf/test_export_100k.py::test_p95_and_mem_budget"],
    "quality_gates": [
        "tests/ci/test_strict_score_guard.py::test_summary_parse_and_evidence",
        "tests/ci/test_no_warnings_gate.py::test_warnings_are_errors",
    ],
}


def _build_full_evidence() -> EvidenceMatrix:
    matrix = EvidenceMatrix()
    for key, entries in EVIDENCE_FIXTURE.items():
        for entry in entries:
            matrix.add(key, entry)
    return matrix


def _feature_flags() -> Dict[str, bool]:
    return {
        "state_cleanup": True,
        "retry_mechanism": True,
        "debug_helpers": True,
        "middleware_order": True,
        "concurrent_safety": True,
        "timing_controls": True,
        "rate_limit_awareness": True,
        "gui_scope": False,
    }


def test_warning_cap_applies() -> None:
    evidence = _build_full_evidence()
    features = _feature_flags()
    engine = ScoreEngine(gui_in_scope=features["gui_scope"], evidence=evidence)
    statuses = engine.apply_evidence_matrix()
    assert all(statuses.values()), "expected all spec evidence present"
    engine.apply_feature_flags(features)
    engine.apply_todo_count(0)
    engine.apply_pytest_result(
        summary={"passed": 12, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "warnings": 2},
        returncode=0,
    )
    engine.apply_state(redis_error=None)
    score = engine.finalize()
    assert any(limit == 90 for limit, _ in score.caps), "warnings must enforce 90 cap"
    assert score.total <= 90
