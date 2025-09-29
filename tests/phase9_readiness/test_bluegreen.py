from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.usefixtures("frozen_time")
def test_blue_green_no_downtime(orchestrator, clean_state, metrics):
    evidence_dir = clean_state["reports"]
    prepare_calls = []
    verify_calls = []
    switch_calls = []

    def prepare():
        prepare_calls.append("prepare")
        manifest = Path(evidence_dir / "bundle" / "manifest.json")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"sha256": "a" * 64}), encoding="utf-8")
        return {"slot": "blue", "manifest": str(manifest)}

    def verify(slot: str):
        verify_calls.append(slot)
        return {"ready": True, "p95_ms": 120.0, "errors": 0}

    def switch(slot: str):
        switch_calls.append(slot)
        return {"switched": True}

    def rollback(slot: str):
        raise AssertionError("rollback should not run")

    evidence = orchestrator.execute_blue_green(
        prepare=prepare,
        switch=switch,
        verify=verify,
        rollback=rollback,
        correlation_id="rid-phase9-bluegreen",
    )
    assert evidence["slot"] == "blue"
    assert evidence["readiness_p95_ms"] < 200

    report_path = evidence_dir / "bluegreen_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["correlation_id"] == "rid-phase9-bluegreen"

    samples = metrics.bluegreen_rollbacks.collect()[0].samples
    assert any(sample.labels["outcome"] == "success" for sample in samples)

    duration_labels = {sample.labels["stage"] for sample in metrics.stage_duration.collect()[0].samples}
    assert {"bluegreen.prepare", "bluegreen.verify", "bluegreen.switch"}.issubset(duration_labels)
