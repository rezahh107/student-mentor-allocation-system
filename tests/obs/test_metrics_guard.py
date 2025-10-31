from __future__ import annotations

import os

import pytest

from tools.reqs_doctor.obs import DoctorMetrics, serve_metrics_guarded


@pytest.fixture()
def metrics_setup(monkeypatch):
    original = os.environ.get("METRICS_TOKEN")
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    yield original
    if original is None:
        monkeypatch.delenv("METRICS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("METRICS_TOKEN", original)


def test_metrics_endpoint_is_public(monkeypatch, metrics_setup):
    metrics = DoctorMetrics.fresh()

    metrics.observe_plan()
    status, headers, payload = serve_metrics_guarded(
        metrics,
        headers={},
    )
    assert status == 200
    assert headers["Content-Type"].startswith("text/plain")
    assert b"reqs_doctor" in payload
