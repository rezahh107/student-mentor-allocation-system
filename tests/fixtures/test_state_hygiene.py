"""State hygiene guarantees around security tooling and Redis fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import fakeredis
import pytest

import scripts.run_bandit_gate as bandit_gate


@pytest.fixture
def redis_namespace() -> fakeredis.FakeStrictRedis:
    client = fakeredis.FakeStrictRedis()
    assert client.dbsize() == 0
    yield client
    client.flushdb()
    assert client.dbsize() == 0


def test_redis_cleaned_per_test(redis_namespace: fakeredis.FakeStrictRedis) -> None:
    redis_namespace.set("security:test", "1")
    assert redis_namespace.dbsize() == 1


def test_redis_namespace_isolation(redis_namespace: fakeredis.FakeStrictRedis) -> None:
    redis_namespace.set("security:ns1", "1")
    other = fakeredis.FakeStrictRedis()
    other.set("security:ns2", "1")
    keys_primary = {key.decode() for key in redis_namespace.scan_iter()}
    keys_other = {key.decode() for key in other.scan_iter()}
    assert keys_primary == {"security:ns1"}
    assert keys_other == {"security:ns2"}


def test_bandit_atomic_write_cleanup(tmp_path: Path) -> None:
    target = tmp_path / "reports" / "bandit.json"
    payload = json.dumps({"results": [], "errors": []})
    bandit_gate._atomic_write(target, payload)  # pylint: disable=protected-access
    files = list(target.parent.iterdir())
    assert files == [target]
    assert target.read_text(encoding="utf-8") == payload
