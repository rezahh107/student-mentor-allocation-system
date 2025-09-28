from __future__ import annotations

from typing import Dict

from tools.strict_score_core import EvidenceMatrix, ScoreEngine

from .test_strict_score_caps import EVIDENCE_FIXTURE, _feature_flags


def _build_evidence_missing(key_to_skip: str) -> EvidenceMatrix:
    matrix = EvidenceMatrix()
    for key, entries in EVIDENCE_FIXTURE.items():
        if key == key_to_skip:
            continue
        for entry in entries:
            matrix.add(key, entry)
    return matrix


def test_missing_spec_triggers_deduction() -> None:
    evidence = _build_evidence_missing("observability_metrics")
    features: Dict[str, bool] = _feature_flags()
    engine = ScoreEngine(gui_in_scope=features["gui_scope"], evidence=evidence)
    statuses = engine.apply_evidence_matrix()
    assert not statuses["observability_metrics"], "observability evidence should be missing"
    engine.apply_feature_flags(features)
    engine.apply_todo_count(0)
    engine.apply_pytest_result(
        summary={"passed": 8, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0, "warnings": 0},
        returncode=0,
    )
    engine.apply_state(redis_error=None)
    score = engine.finalize()
    assert any("Missing evidence" in reason for _, _, reason in score.deductions)
    assert score.next_actions, "missing evidence must populate next actions"
    assert score.total < 100
