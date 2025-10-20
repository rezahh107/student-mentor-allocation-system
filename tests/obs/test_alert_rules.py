from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sma.phase7_release.release_builder import ReleaseBuilder

from tests.phase7_utils import FakeDistribution


@pytest.fixture
def clean_state():
    yield


def test_prometheus_rules_loaded(tmp_path, monkeypatch, clean_state):
    dists = [FakeDistribution(name="alpha", release="1.0.0")]
    monkeypatch.setattr("sma.phase7_release.lockfiles.importlib_metadata.distributions", lambda: dists)
    monkeypatch.setattr("sma.phase7_release.sbom.importlib_metadata.distributions", lambda: dists)
    builder = ReleaseBuilder(
        project_root=Path.cwd(),
        env={"GIT_SHA": "f00dbabe99887766"},
        clock=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    artifacts = builder.build(tmp_path)
    rules = artifacts.prometheus_rules.read_text("utf-8")
    assert "SabtExporterLatencyHigh" in rules
    assert "export_job_retry_exhausted_total" in rules
