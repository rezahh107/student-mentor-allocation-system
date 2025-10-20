from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from sma.core.clock import Clock, FrozenClock
from sma.infrastructure.api.routes import create_app
from sma.web.deps.clock import override_clock


class _StubRedisClient:
    def __init__(self) -> None:
        self.storage: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.storage[key] = self.storage.get(key, 0) + 1
        return self.storage[key]

    def expire(self, key: str, ttl: int) -> bool:
        self.storage.setdefault(f"expire::{key}", ttl)
        return True


class _StubRedisModule:
    def __init__(self, bucket: list[_StubRedisClient]) -> None:
        self._bucket = bucket

    class Redis:
        @staticmethod
        def from_url(*_args: Any, **_kwargs: Any) -> _StubRedisClient:
            raise RuntimeError("stub not initialised")

    def bind(self) -> None:
        module = self

        class _RedisWrapper:
            @staticmethod
            def from_url(*_args: Any, **_kwargs: Any) -> _StubRedisClient:
                client = _StubRedisClient()
                module._bucket.append(client)
                return client

        self.Redis = _RedisWrapper  # type: ignore[assignment]


def test_middleware_chain_uses_injected_clock(monkeypatch, clock_test_context):
    frozen = FrozenClock(timezone=Clock.for_tehran().timezone)
    frozen.set(datetime(2024, 3, 20, 12, 0, tzinfo=frozen.timezone))
    redis_clients: list[_StubRedisClient] = []
    stub_module = _StubRedisModule(redis_clients)
    stub_module.bind()
    monkeypatch.setattr("sma.infrastructure.security.rate_limit.redis", stub_module, raising=False)

    with override_clock(frozen):
        app = create_app()
        with TestClient(app) as client:
            def _invoke() -> TestClient:
                response = client.get(
                    "/metrics",
                    headers={"X-Metrics-Token": "metrics-token", "X-Api-Key": "test-key"},
                )
                if response.status_code != 200:
                    debug = clock_test_context["get_debug_context"]()
                    raise AssertionError(f"Unexpected status={response.status_code} context={debug}")
                clock_test_context["cleanup_log"].append("metrics-request")
                bucket = redis_clients[0].storage if redis_clients else {}
                expected_slot = int(frozen.now().timestamp()) // 60
                key = f"ratelimit:test-key:{expected_slot}"
                assert bucket.get(key, 0) >= 1, bucket
                assert response.headers.get("X-Middleware-Chain") == "RateLimit,Idempotency,Auth"
                return response

            response = clock_test_context["retry"](_invoke)
            assert response is not None
