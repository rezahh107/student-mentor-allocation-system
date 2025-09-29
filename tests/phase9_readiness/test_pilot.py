from __future__ import annotations

import json
from hashlib import sha256

import pytest


@pytest.mark.usefixtures("frozen_time")
def test_pilot_slo_compliance(orchestrator, clean_state, metrics, retry_waits):
    dataset_rows = [f"row-{idx}\n".encode("utf-8") for idx in range(10)]
    upload_calls = {"count": 0}

    def upload(chunks):
        upload_calls["count"] += 1
        if upload_calls["count"] == 1:
            raise RuntimeError("transient")
        total = sum(len(chunk) for chunk in chunks)
        return {"duration": 0.4, "memory": 45.0, "errors": [], "size": total}

    def validate():
        return {"duration": 0.6, "memory": 55.0, "errors": []}

    def activate():
        return {"duration": 0.8, "memory": 60.0, "errors": []}

    def export():
        payload = b";".join(dataset_rows)
        return {"duration": 0.9, "memory": 70.0, "errors": [], "manifest": sha256(payload).hexdigest()}

    report = orchestrator.run_pilot(
        dataset=dataset_rows,
        upload=upload,
        validate=validate,
        activate=activate,
        export=export,
        correlation_id="rid-phase9-pilot",
    )
    assert report.dataset_bytes > 0
    assert report.row_count == len(dataset_rows)
    assert report.dataset_checksum
    assert report.stream_elapsed_seconds >= 0.0
    assert report.slo_p95_seconds <= 0.9
    assert report.peak_memory_mb <= 70.0
    assert report.total_errors == 0

    waits = list(retry_waits)
    assert waits and waits[0] > 0.05

    metrics_samples = metrics.pilot_runs.collect()[0].samples
    assert any(sample.labels["namespace"] for sample in metrics_samples)

    duration_samples = metrics.stage_duration.collect()[0].samples
    labels = {sample.labels["stage"] for sample in duration_samples}
    assert {"pilot.upload", "pilot.validate", "pilot.activate", "pilot.export"}.issubset(labels)

    payload = json.loads((clean_state["reports"] / "pilot_report.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == report.run_id
    assert payload["correlation_id"] == "rid-phase9-pilot"
    assert payload["row_count"] == len(dataset_rows)
    assert payload["dataset_bytes"] == report.dataset_bytes
