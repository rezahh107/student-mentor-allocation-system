from __future__ import annotations

import pytest

from sma.phase7_release.deploy import ReadinessGate, ZeroDowntimeHandoff


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_readiness_gate_and_handoff(tmp_path, clean_state):
    current = 0.0

    def clock() -> float:
        return current

    gate = ReadinessGate(clock=clock, readiness_timeout=5.0)
    gate.record_dependency(name="redis", healthy=True)
    gate.record_dependency(name="database", healthy=True)
    assert not gate.ready()
    gate.record_cache_warm()
    assert gate.ready()

    releases_dir = tmp_path / "releases"
    lock = tmp_path / "lock"
    handoff = ZeroDowntimeHandoff(
        releases_dir=releases_dir,
        lock_file=lock,
        clock=clock,
        sleep=lambda _: None,
    )
    source = tmp_path / "build-A"
    source.mkdir()
    result = handoff.promote(build_id="build-A", source=source)
    assert result.current_target == source
    assert (releases_dir / "current").resolve() == source
