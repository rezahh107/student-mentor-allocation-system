from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from sma.phase7_release.sbom import generate_sbom

from tests.phase7_utils import FakeDistribution


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_cyclonedx_schema_and_contents(tmp_path, monkeypatch, clean_state):
    dists = [
        FakeDistribution(name="alpha", release="1.0.0"),
        FakeDistribution(name="beta", release="2.0.0"),
    ]
    path = tmp_path / "sbom.json"
    clock_now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    components = generate_sbom(path, distributions=dists, clock=lambda: clock_now)
    payload = json.loads(path.read_text("utf-8"))

    assert payload["bomFormat"] == "CycloneDX"
    assert payload["metadata"]["timestamp"] == clock_now.isoformat()
    assert len(payload["components"]) == 2
    assert all(component.hash_value for component in components)
