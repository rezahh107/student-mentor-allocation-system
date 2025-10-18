from __future__ import annotations

import hashlib
import uuid
from typing import Dict

import pytest
from fakeredis import FakeStrictRedis

try:  # pragma: no cover - prefer real dependency when available
    from freezegun import freeze_time
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal envs
    from contextlib import contextmanager

    @contextmanager
    def freeze_time(*args, **kwargs):  # type: ignore[override]
        yield

from repo_auditor_lite.metrics import reset_registry


@pytest.fixture(autouse=True)
def fresh_metrics_registry() -> None:
    reset_registry()
    yield
    reset_registry()


@pytest.fixture()
def redis_client() -> FakeStrictRedis:
    client = FakeStrictRedis()
    client.flushall()
    yield client
    client.flushall()


@pytest.fixture()
def clean_state(redis_client: FakeStrictRedis, tmp_path_factory: pytest.TempPathFactory) -> Dict[str, object]:
    redis_client.flushall()
    context = {
        "redis": redis_client,
        "tmp": tmp_path_factory.mktemp(f"repo-auditor-{uuid.uuid4().hex}")
    }
    yield context
    redis_client.flushall()


@pytest.fixture()
def frozen_clock():
    with freeze_time("2024-01-01 00:00:00", tz_offset=3.5):
        yield


@pytest.fixture()
def unique_namespace() -> str:
    token = uuid.uuid4().hex
    hashed = hashlib.blake2s(token.encode("utf-8"), digest_size=6).hexdigest()
    return f"ns-{hashed}"
