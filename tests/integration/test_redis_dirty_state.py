"""Integration tests ensuring Redis state hygiene via fakeredis."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Dict

import fakeredis
import pytest

from sma.phase6_import_to_sabt.app.config import AppConfig
from sma.phase6_import_to_sabt.probes.factories import build_redis_probe
from tests.config.test_env_loading import _build_env, _load_with_retry


@dataclass(slots=True)
class AsyncRedisAdapter:
    """Async wrapper around :class:`fakeredis.FakeStrictRedis` used for probes."""

    namespace: str
    _client: fakeredis.FakeStrictRedis = field(default_factory=fakeredis.FakeStrictRedis)

    async def ping(self) -> bool:
        ping = getattr(self._client, "ping", None)
        if callable(ping):
            ping()
        else:
            sentinel = f"{self.namespace}:ping"
            self._client.set(sentinel, "1")
            self._client.delete(sentinel)
        return True

    async def close(self) -> None:
        return None

    async def flushdb(self) -> None:
        self._client.flushdb()

    def keys(self, pattern: str) -> list[str]:
        return [str(key) for key in self._client.keys(pattern)]

    def set_dirty(self, key: str, value: str) -> None:
        self._client.set(key, value)

    @property
    def raw(self) -> fakeredis.FakeStrictRedis:
        return self._client


@pytest.fixture(autouse=True)
def import_to_sabt_env_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ImportToSabt prefixed variables are reset before/after each test."""

    preserved = {k: v for k, v in os.environ.items() if k.startswith("IMPORT_TO_SABT_")}
    for key in list(preserved):
        monkeypatch.delenv(key, raising=False)
    yield
    for key in list(os.environ):
        if key.startswith("IMPORT_TO_SABT_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in preserved.items():
        monkeypatch.setenv(key, value)


@pytest.mark.integration
@pytest.mark.redis
def test_config_loads_with_clean_and_dirty_redis_state(
    clean_state,
    monkeypatch: pytest.MonkeyPatch,
    get_debug_context,
    timing_control,
) -> None:
    """Config loading and Redis probes must tolerate dirty state without real services."""

    namespace = f"{clean_state['redis'].namespace}:redis"
    env_map: Dict[str, str] = _build_env(namespace)
    for key, value in env_map.items():
        monkeypatch.setenv(key, value)

    adapter = AsyncRedisAdapter(namespace=namespace)
    asyncio.run(adapter.flushdb())

    monkeypatch.setattr(
        "sma.phase6_import_to_sabt.probes.factories.Redis.from_url",
        lambda url, decode_responses=True: adapter,
    )

    cfg: AppConfig = _load_with_retry()
    assert cfg.redis.namespace == namespace

    async def _controlled_sleep(delay: float) -> None:
        timing_control.advance(delay)

    probe = build_redis_probe(
        cfg.redis.dsn,
        client_factory=lambda url: adapter,
        sleeper=_controlled_sleep,
    )

    async def _execute_probe() -> bool:
        result = await probe(timeout=0.1)
        diagnostics = get_debug_context(
            request={"probe": "redis", "namespace": namespace},
            response={"detail": result.detail},
            extra={"env": env_map, "dirty_keys": adapter.keys("*")},
        )
        assert result.healthy, f"Probe failed under dirty state: {diagnostics}"
        return result.healthy

    clean_result = asyncio.run(probe(timeout=0.1))
    assert clean_result.healthy, "Clean Redis probe unexpectedly failed"
    adapter.set_dirty(f"{namespace}:leaked", "1")
    asyncio.run(_execute_probe())
    asyncio.run(adapter.flushdb())
