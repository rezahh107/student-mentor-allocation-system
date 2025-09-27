from __future__ import annotations

from pathlib import Path

import pytest

from src.phase7_release.dependency_guard import LockedDependencyError, enforce_runtime_dependencies

from tests.phase7_utils import FakeDistribution


@pytest.fixture
def clean_state(tmp_path):
    yield


def _write_lock(path: Path, entries: dict[str, str]) -> None:
    lines = []
    for name, version in entries.items():
        normalized = name.replace("-", "_")
        lines.append(f"{normalized}=={version} --hash=sha256:digest-{normalized}-{version}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_locked_imports_enforced(tmp_path, clean_state):
    lock_path = tmp_path / "requirements.lock"
    _write_lock(lock_path, {"alpha": "1.0.0"})

    enforce_runtime_dependencies(
        lockfile_path=lock_path,
        distributions=[FakeDistribution(name="alpha", release="1.0.0")],
    )

    with pytest.raises(LockedDependencyError) as exc:
        enforce_runtime_dependencies(
            lockfile_path=lock_path,
            distributions=[FakeDistribution(name="alpha", release="2.0.0")],
        )
    assert "RELEASE_DEP_MISMATCH" in str(exc.value)
