import time
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
import redis
from redis.asyncio import Redis

from sma.hardened_api.api import APISettings, create_app
from sma.hardened_api.middleware import (
    AuthConfig,
    ensure_rate_limit_config_restored,
    restore_rate_limit_config,
    snapshot_rate_limit_config,
)
from sma.hardened_api.observability import get_metric
from sma.hardened_api.redis_support import RedisNamespaces
from tests.hardened_api.conftest import (
    FakeAllocator,
    get_debug_context,
    setup_test_data,
    verify_middleware_order,
    temporary_rate_limit_config,
)
from tests.hardened_api.redis_launcher import (
    RedisLaunchSkipped,
    RedisRuntime,
    launch_redis_server,
)


@pytest.fixture(scope="session")
def redis_runtime() -> RedisRuntime:
    try:
        with launch_redis_server() as runtime:
            yield runtime
    except RedisLaunchSkipped as skipped:
        pytest.xfail(f"redis launcher skipped: {skipped}")


@pytest.fixture(scope="function")
def live_redis(redis_runtime: RedisRuntime) -> str:
    sync_client = redis.Redis.from_url(redis_runtime.url)
    try:
        sync_client.ping()
    except redis.RedisError as exc:  # pragma: no cover - integration guard
        raise RuntimeError("Redis server unavailable") from exc
    sync_client.flushdb()
    yield redis_runtime.url
    sync_client.flushdb()
    sync_client.close()


@pytest_asyncio.fixture(scope="function")
async def real_client(
    live_redis: str, allocator: FakeAllocator, auth_config: AuthConfig
) -> AsyncClient:
    settings = APISettings(
        redis_url=live_redis,
        redis_namespace=f"itest:{uuid.uuid4()}",
        rate_limit_fail_open=False,
        idempotency_ttl_seconds=3,
    )
    app = create_app(
        allocator=allocator,
        settings=settings,
        auth_config=auth_config,
    )
    config = app.state.middleware_state.rate_limit_config  # type: ignore[attr-defined]
    snapshot = snapshot_rate_limit_config(config)
    verify_middleware_order(app)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    redis_conn = app.state.api_state.redis_client  # type: ignore[attr-defined]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        setattr(client, "app", app)
        try:
            yield client
            ensure_rate_limit_config_restored(
                config,
                snapshot,
                context="real_client fixture",
            )
        finally:
            restore_rate_limit_config(config, snapshot)
            await redis_conn.aclose()


def _auth_headers(auth_config: AuthConfig) -> dict[str, str]:
    raw_key = "STATICKEY1234567890"
    return {
        "Content-Type": "application/json; charset=utf-8",
        "X-API-Key": raw_key,
    }


@pytest.mark.asyncio
async def test_real_idempotency_replay(real_client: AsyncClient, live_redis: str, auth_config: AuthConfig):
    headers = _auth_headers(auth_config)
    payload = setup_test_data("901")
    payload["phone"] = "09121234567"
    idempotency_key = "AbCdEfGhIjKlMnOp"
    headers["Idempotency-Key"] = idempotency_key

    first = await real_client.post("/allocations", json=payload, headers=headers)
    assert first.status_code == 200, get_debug_context(real_client.app)

    second = await real_client.post("/allocations", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json() == first.json()

    namespace = RedisNamespaces(real_client.app.state.api_state.settings.redis_namespace)  # type: ignore[attr-defined]
    redis_key = namespace.idempotency(idempotency_key)
    async_client = Redis.from_url(live_redis, encoding="utf-8", decode_responses=False)
    ttl = await async_client.ttl(redis_key)
    await async_client.aclose()
    assert ttl == pytest.approx(real_client.app.state.api_state.settings.idempotency_ttl_seconds, rel=0.2)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_retry_exhaustion_logs_and_metrics(live_redis: str, auth_config: AuthConfig, caplog):
    class FlakyRedis:
        def __init__(self, delegate: Redis) -> None:
            self._delegate = delegate
            self.failures = 3

        async def set(self, name: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
            if "idem_lock" in name and self.failures:
                self.failures -= 1
                raise TimeoutError("redis unavailable")
            return await self._delegate.set(name, value, ex=ex, nx=nx)

        def __getattr__(self, item):
            return getattr(self._delegate, item)

    base_client = Redis.from_url(live_redis, encoding="utf-8", decode_responses=False)
    flaky_client = FlakyRedis(base_client)
    settings = APISettings(
        redis_url="",
        redis_namespace=f"itest:{uuid.uuid4()}",
        rate_limit_fail_open=False,
    )
    allocator = FakeAllocator()
    app = create_app(
        allocator=allocator,
        settings=settings,
        auth_config=auth_config,
        redis_client=flaky_client,
    )
    verify_middleware_order(app)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        setattr(client, "app", app)
        caplog.set_level("WARNING", logger="hardened_api.redis")
        headers = _auth_headers(auth_config)
        headers["Idempotency-Key"] = "FlakyIdemKey1234"
        payload = setup_test_data("902")

        response = await client.post("/allocations", json=payload, headers=headers)
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL"
        assert "redis.retry_exhausted" in caplog.text

    attempts_metric = get_metric("redis_retry_attempts_total").labels(op="idempotency.lock", outcome="error")
    assert attempts_metric._value.get() >= 3
    exhausted_metric = get_metric("redis_retry_exhausted_total").labels(op="idempotency.lock", outcome="error")
    assert exhausted_metric._value.get() >= 1
    await base_client.aclose()


@pytest.mark.asyncio
async def test_idempotency_ttl_expiry(
    real_client: AsyncClient, live_redis: str, auth_config: AuthConfig, allocator: FakeAllocator
):
    headers = _auth_headers(auth_config)
    headers["Idempotency-Key"] = "ExpireKeyXYZ12345"
    payload = setup_test_data("903")

    response = await real_client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 200

    namespace = RedisNamespaces(real_client.app.state.api_state.settings.redis_namespace)  # type: ignore[attr-defined]
    redis_key = namespace.idempotency(headers["Idempotency-Key"])
    lock_key = namespace.idempotency_lock(headers["Idempotency-Key"])
    async_client = Redis.from_url(live_redis, encoding="utf-8", decode_responses=False)
    await async_client.expire(redis_key, 0)
    await async_client.expire(lock_key, 0)
    await async_client.aclose()

    replay = await real_client.post("/allocations", json=payload, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["allocation_id"] != response.json()["allocation_id"]
    assert len(allocator.calls) == 2


@pytest.mark.asyncio
async def test_rate_limit_fail_open_get_fail_closed_post(live_redis: str, auth_config: AuthConfig):
    class BrokenRedis:
        def __init__(self, delegate: Redis) -> None:
            self._delegate = delegate

        async def zcard(self, name: str) -> int:
            raise TimeoutError("limiter broken")

        async def zremrangebyscore(self, *args, **kwargs):
            raise TimeoutError("limiter broken")

        def __getattr__(self, item):
            return getattr(self._delegate, item)

    base_client = Redis.from_url(live_redis, encoding="utf-8", decode_responses=False)
    broken_client = BrokenRedis(base_client)
    settings = APISettings(
        redis_url="",
        redis_namespace=f"itest:{uuid.uuid4()}",
        rate_limit_fail_open=False,
    )
    allocator = FakeAllocator()
    app = create_app(
        allocator=allocator,
        settings=settings,
        auth_config=auth_config,
        redis_client=broken_client,
    )
    verify_middleware_order(app)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        setattr(client, "app", app)
        headers = _auth_headers(auth_config)
        get_response = await client.get("/status", headers=headers)
        assert get_response.status_code == 200

        headers["Idempotency-Key"] = "BrokenLimiterKey123"
        post_response = await client.post("/allocations", json=setup_test_data("904"), headers=headers)
        assert post_response.status_code == 500
    await base_client.aclose()


@pytest.mark.asyncio
async def test_perf_budget_under_load(real_client: AsyncClient, auth_config: AuthConfig, allocator: FakeAllocator):
    headers = _auth_headers(auth_config)
    headers["Idempotency-Key"] = "PerfBudgetKey12345"
    payload = setup_test_data("905")

    durations: list[float] = []
    with temporary_rate_limit_config(real_client.app) as config:
        # widen per-route limit to observe latency budget without 429 noise
        config.per_route["/allocations"].requests = 30

        for iteration in range(10):
            headers["Idempotency-Key"] = f"PerfBudgetKey12345-{iteration}"
            start = time.perf_counter()
            response = await real_client.post("/allocations", json=payload, headers=headers)
            duration = time.perf_counter() - start
            durations.append(duration)
            assert response.status_code == 200, get_debug_context(real_client.app)
    durations.sort()
    p95_index = max(0, int(len(durations) * 0.95) - 1)
    assert durations[p95_index] < 0.2, durations
    assert len(allocator.calls) == 10
