from __future__ import annotations

import os
import uuid

import fakeredis
import pytest

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
