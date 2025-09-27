from __future__ import annotations

import pytest

from src.phase7_release.deploy import ZeroDowntimeHandoff


@pytest.fixture
def clean_state(tmp_path):
    yield


def test_atomic_symlink_swap(tmp_path, clean_state):
    releases = tmp_path / "releases"
    handoff = ZeroDowntimeHandoff(
        releases_dir=releases,
        lock_file=tmp_path / "lock",
        clock=lambda: 0.0,
        sleep=lambda _: None,
    )
    build_a = tmp_path / "build-a"
    build_a.mkdir()
    build_b = tmp_path / "build-b"
    build_b.mkdir()

    result_a = handoff.promote(build_id="A", source=build_a)
    assert result_a.previous_target is None
    assert (releases / "current").resolve() == build_a

    result_b = handoff.promote(build_id="B", source=build_b)
    assert result_b.previous_target == build_a
    assert (releases / "previous").resolve() == build_a
    assert (releases / "current").resolve() == build_b
