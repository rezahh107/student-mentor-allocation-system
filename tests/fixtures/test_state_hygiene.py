"""State hygiene guarantees around security tooling and Redis fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from prometheus_client import Counter

import scripts.run_bandit_gate as bandit_gate

try:
    import fakeredis  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback to local stub
    from sma import fakeredis  # type: ignore


@pytest.fixture
def redis_namespace() -> fakeredis.FakeStrictRedis:
    client = fakeredis.FakeStrictRedis()
    client.flushdb()
    assert not list(client.scan_iter())
    yield client
    client.flushdb()
    assert not list(client.scan_iter())


def test_redis_cleaned_per_test(redis_namespace: fakeredis.FakeStrictRedis) -> None:
    redis_namespace.set("security:test", "1")
    assert list(redis_namespace.scan_iter()) == ["security:test"]


def test_redis_namespace_isolation(redis_namespace: fakeredis.FakeStrictRedis) -> None:
    redis_namespace.set("security:ns1", "1")
    other = fakeredis.FakeStrictRedis()
    other.set("security:ns2", "1")
    keys_primary = {key for key in redis_namespace.scan_iter()}
    keys_other = {key for key in other.scan_iter()}
    assert keys_primary == {"security:ns1"}
    assert keys_other == {"security:ns2"}


def test_bandit_atomic_write_cleanup(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "bandit.json"
    payload = json.dumps({"results": [], "errors": []})
    bandit_gate._atomic_write(target, payload)  # pylint: disable=protected-access
    files = list(target.parent.iterdir())
    assert files == [target]
    assert target.read_text(encoding="utf-8") == payload


def test_redis_and_registry_cleanup(cleanup_fixtures) -> None:
    cleanup = cleanup_fixtures
    cleanup.redis.setnx("state:temp", "1")
    marker = Counter("state_test_total", "state hygiene test counter", registry=cleanup.registry)
    marker.inc()
    assert cleanup.redis.get("state:temp") == "1"
    assert any(metric.samples for metric in cleanup.registry.collect())
    cleanup.flush_state()
    assert cleanup.redis.get("state:temp") is None
    assert not list(cleanup.registry.collect())
