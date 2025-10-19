from __future__ import annotations

import os

import pytest
from prometheus_client import CollectorRegistry

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


def test_metrics_requires_token_and_rejects_missing_or_wrong(monkeypatch, metrics_setup):
    registry = CollectorRegistry()
    metrics = DoctorMetrics(registry)

    status, _, body = serve_metrics_guarded(metrics, headers={})
    assert status == 503
    assert "توکن" in body.decode("utf-8")

    monkeypatch.setenv("METRICS_TOKEN", "token-123")

    status, _, body = serve_metrics_guarded(metrics, headers={})
    assert status == 401
    assert "نیازمند" in body.decode("utf-8")

    status, _, body = serve_metrics_guarded(metrics, headers={"X-Metrics-Token": "wrong"})
    assert status == 403
    assert "نامعتبر" in body.decode("utf-8")

    metrics.observe_plan()
    status, headers, payload = serve_metrics_guarded(
        metrics,
        headers={"X-Metrics-Token": "token-123"},
    )
    assert status == 200
    assert headers["Content-Type"].startswith("text/plain")
    assert b"reqs_doctor" in payload
