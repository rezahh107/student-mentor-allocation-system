from __future__ import annotations

import asyncio
from collections import deque

from sma.hardened_api.redis_support import (
    RedisExecutor,
    RedisNamespaces,
    RedisRetryConfig,
    RedisSlidingWindowLimiter,
    create_redis_client,
)


def test_fake_redis_rate_limiter_respects_namespace(monkeypatch, rid: str) -> None:
    monkeypatch.setenv("SMA_TEST_FAKE_REDIS", "1")
    namespace = f"test:{rid}"
    monkeypatch.setenv("SMA_FAKE_REDIS_NAMESPACE", namespace)

    async def _scenario() -> None:
        client = create_redis_client("redis://ignored")
        await client.flushdb()

        namespaces = RedisNamespaces(namespace)
        executor = RedisExecutor(config=RedisRetryConfig(attempts=2), namespace=namespace)
        limiter = RedisSlidingWindowLimiter(
            redis=client,
            namespaces=namespaces,
            executor=executor,
        )

        debug_context = {"namespace": namespace}
        first = await limiter.allow("consumer", "route", requests=1, window_seconds=60, correlation_id=rid)
        assert first.allowed, debug_context

        second = await limiter.allow("consumer", "route", requests=1, window_seconds=60, correlation_id=rid)
        assert not second.allowed, {**debug_context, "retry_after": second.retry_after}

        other_namespace = RedisNamespaces(f"other:{rid}")
        other_executor = RedisExecutor(config=RedisRetryConfig(attempts=1), namespace=f"other:{rid}")
        other_limiter = RedisSlidingWindowLimiter(
            redis=client,
            namespaces=other_namespace,
            executor=other_executor,
        )

        third = await other_limiter.allow(
            "consumer",
            "route",
            requests=1,
            window_seconds=60,
            correlation_id=f"other-{rid}",
        )
        assert third.allowed, {"namespaces": [namespace, other_namespace.base]}

        await client.flushdb()

    asyncio.run(_scenario())


def test_fake_redis_executor_records_attempts(monkeypatch, rid: str) -> None:
    monkeypatch.setenv("SMA_TEST_FAKE_REDIS", "1")
    async def _scenario() -> None:
        client = create_redis_client("redis://unused")
        await client.flushdb()
        namespaces = RedisNamespaces(f"exec:{rid}")
        executor = RedisExecutor(config=RedisRetryConfig(attempts=3), namespace=namespaces.base)

        attempts = deque()

        async def _operation() -> str:
            attempts.append("called")
            return "ok"

        result = await executor.call(_operation, op_name="noop", correlation_id=rid)
        assert result == "ok", {"attempts": list(attempts)}
        await client.flushdb()

    asyncio.run(_scenario())

