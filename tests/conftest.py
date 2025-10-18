from __future__ import annotations

import hashlib
import uuid
from typing import Dict
import os
import uuid

import fakeredis
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
from tooling.clock import Clock
from tooling.metrics import registry_scope

pytest_plugins = [
    "tooling.plugins.xdist_stub",
    "tooling.plugins.timeout_stub",
]


@pytest.fixture(autouse=True)
def _set_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Tehran")


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def redis_client() -> fakeredis.FakeStrictRedis:
    client = fakeredis.FakeStrictRedis()
    client.flushall()
    yield client
    client.flushall()


@pytest.fixture()
def redis_namespace(redis_client: fakeredis.FakeRedis) -> str:
    namespace = f"test:{uuid.uuid4().hex}"
    yield namespace
    for key in list(redis_client.scan_iter(match=f"{namespace}:*")):
        redis_client.delete(key)


@pytest.fixture()
def metrics_registry():
    with registry_scope() as registry:
        yield registry


@pytest.fixture()
def json_report_path(tmp_path):
    path = tmp_path / "pytest.json"
    yield path


@pytest.fixture()
def junit_report_path(tmp_path):
    path = tmp_path / "junit.xml"
    yield path
