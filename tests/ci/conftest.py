"""Shared fixtures for deterministic CI quality gates."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

import pytest

from tests.packaging import conftest as packaging_conftest


@pytest.fixture
def packaging_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[packaging_conftest.PackagingState]:
    """Provide a reusable packaging state with deterministic cleanup."""
    packaging_conftest._cleanup_targets(packaging_conftest.PROJECT_ROOT)
    namespace = hashlib.blake2s(str(tmp_path).encode("utf-8"), digest_size=6).hexdigest()
    workspace = tmp_path / f"wheelhouse-{namespace}"
    workspace.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("TZ", "Asia/Tehran")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1704067200")

    env = dict(os.environ)
    state = packaging_conftest.PackagingState(
        root=packaging_conftest.PROJECT_ROOT,
        env=env,
        namespace=namespace,
        workspace=workspace,
    )
    try:
        yield state
    finally:
        state.cleanup()
        packaging_conftest._cleanup_targets(packaging_conftest.PROJECT_ROOT)
