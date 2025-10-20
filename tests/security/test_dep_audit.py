from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sma.phase7_release.release_builder import ReleaseBuilder

from tests.phase7_utils import FakeDistribution


@pytest.fixture
def clean_state():
    yield


def test_pip_audit_artifact_exists(monkeypatch, tmp_path, clean_state):
    dists = [FakeDistribution(name="alpha", release="1.0.0")]
    monkeypatch.setattr("sma.phase7_release.lockfiles.importlib_metadata.distributions", lambda: dists)
    monkeypatch.setattr("sma.phase7_release.sbom.importlib_metadata.distributions", lambda: dists)

    builder = ReleaseBuilder(
        project_root=Path.cwd(),
        env={"GIT_SHA": "0011223344556677"},
        clock=lambda: datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    artifacts = builder.build(tmp_path)

    audit_path = artifacts.vulnerability_report
    data = json.loads(audit_path.read_text("utf-8"))
    assert data["tool"] == "pip-audit-stub"
    assert data["packages"] == ["alpha"]
