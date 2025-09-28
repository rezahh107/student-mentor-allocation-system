from __future__ import annotations

from typing import Dict

from tools.strict_score_core import EvidenceMatrix, ScoreEngine


EVIDENCE_FIXTURE: Dict[str, list[str]] = {
    "middleware_order": ["tests/mw/test_order_with_xlsx_ci.py::test_middleware_order"],
    "deterministic_clock": ["tests/time/test_clock_tz_ci.py::test_tehran_clock_injection"],
    "state_hygiene": ["tests/hygiene/test_registry_reset.py::test_prom_registry_reset"],
    "observability": ["tests/obs/test_metrics_format_label_ci.py::test_json_logs_masking"],
    "excel_safety": ["tests/exports/test_excel_safety_ci.py::test_formula_guard"],
    "atomic_io": ["tests/readiness/test_atomic_io.py::test_atomic_write_and_rename"],
    "performance_budgets": ["tests/perf/test_ci_overhead.py::test_orchestrator_overhead"],
    "persian_errors": ["tests/logging/test_persian_errors.py::test_error_envelopes"],
    "counter_rules": ["tests/obs_e2e/test_metrics_labels.py::test_retry_exhaustion_counters"],
    "normalization": ["tests/ci/test_strict_score_guard.py::test_parse_pytest_summary_extended_handles_persian_digits"],
    "export_streaming": ["tests/exports/test_excel_safety_ci.py::test_formula_guard"],
    "release_artifacts": ["tests/ci/test_ci_pytest_runner.py::test_strict_mode"],
    "academic_year_provider": ["tests/ci/test_ci_pytest_runner.py::test_strict_mode"],
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
