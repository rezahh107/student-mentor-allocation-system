from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sma.phase7_release.release_builder import ReleaseBuilder
from sma.phase7_release.hashing import sha256_file

from tests.phase7_utils import FakeDistribution


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_all_artifacts_sha256(monkeypatch, tmp_path, clean_state):
    dists = [
        FakeDistribution(name="alpha", release="1.0.0"),
        FakeDistribution(name="beta", release="2.5.1"),
    ]
    monkeypatch.setattr("sma.phase7_release.lockfiles.importlib_metadata.distributions", lambda: dists)
    monkeypatch.setattr("sma.phase7_release.sbom.importlib_metadata.distributions", lambda: dists)

    clock_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    builder = ReleaseBuilder(
        project_root=Path.cwd(),
        env={"GIT_SHA": "cafebabe12345678", "BUILD_TAG": "v1.2.3"},
        clock=lambda: clock_time,
    )
    artifacts = builder.build(tmp_path)

    manifest_data = json.loads(artifacts.release_manifest.read_text("utf-8"))
    hashes = []
    for entry in manifest_data["artifacts"]:
        file_path = artifacts.release_manifest.parent / entry["name"]
        hashes.append(entry["sha256"])
        assert entry["sha256"] == sha256_file(file_path)
    assert manifest_data["artifact_ids"] == hashes
    assert manifest_data["version"].startswith("1.2.3")
