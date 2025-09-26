from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Iterator, cast
from uuid import uuid4

import pytest
from prometheus_client import CollectorRegistry

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import httpx


class ClosingASGITransport(httpx.ASGITransport):
    """ASGI transport that exposes a synchronous close method."""

    def close(self) -> None:  # type: ignore[override]
        try:
            asyncio.run(super().aclose())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(super().aclose())
            finally:
                loop.close()

USE_REDIS_STUB = os.getenv("TEST_REDIS_STUB", "0") == "1"
if TYPE_CHECKING:
    import redis as redis_type  # pragma: no cover
else:
    redis_type = None  # type: ignore

if USE_REDIS_STUB:
    os.environ.setdefault("TEST_REDIS_STUB", "1")
    from src.api import redis_stub

    redis = redis_stub.redis_sync  # type: ignore[assignment]
    pytestmark = pytest.mark.stub
else:  # pragma: no cover - optional dependency guard
    try:
        import redis  # type: ignore
    except Exception:  # pragma: no cover - dependency missing
        redis = None

if TYPE_CHECKING:
    from redis import Redis  # type: ignore

from src.api.api import HardenedAPIConfig, create_app  # noqa: E402
from src.api.middleware import StaticCredential  # noqa: E402
from src.phase3_allocation import AllocationRequest, AllocationResult  # noqa: E402


class RedisCountingAllocator:
    def __init__(self, redis_url: str, namespace: str) -> None:
        if redis is None:  # pragma: no cover - dependency guard
            raise RuntimeError('redis extra not installed')
        self._redis_url = redis_url
        self._namespace = namespace

    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        client = redis.Redis.from_url(self._redis_url)
        try:
            client.incr(f"{self._namespace}:allocations")
        finally:
            client.close()
        return AllocationResult(
            allocation_id=1,
            allocation_code="2301",
            year_code="23",
            mentor_id=request.mentor_id,
            status="OK",
            message="",
            error_code=None,
            idempotency_key="idem-distributed",
            outbox_event_id="evt",
            dry_run=False,
        )


class CountingAllocator:
    def __init__(self) -> None:
        self.calls: list[AllocationRequest] = []
        self.message: str = ""

    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        self.calls.append(request)
        return AllocationResult(
            allocation_id=len(self.calls),
            allocation_code="2301",
            year_code="23",
            mentor_id=request.mentor_id,
            status="OK",
            message=self.message,
            error_code=None,
            idempotency_key=f"idem-{len(self.calls)}",
            outbox_event_id="evt",
            dry_run=False,
        )


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    if USE_REDIS_STUB:
        url = "redis+stub://default"
        client = redis.Redis.from_url(url)
        client.flushdb()
        yield url
        client.flushdb()
        return
    if redis is None:
        pytest.xfail(
            "redis extra not installed. Install redis>=5 or set TEST_REDIS_STUB=1 for stub smoke tests.",
        )
    redis_url_value = os.environ.get("REDIS_URL")
    if not redis_url_value:
        pytest.xfail(
            "REDIS_URL not configured. Provide a Redis service or export TEST_REDIS_STUB=1 to run stub tests.",
        )
        raise AssertionError("redis url must be provided")
    url = cast(str, redis_url_value)
    client = redis.Redis.from_url(url)
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover - network issues
        pytest.xfail(f"redis not available: {exc}. Ensure service is running or set TEST_REDIS_STUB=1.")
    client.flushdb()
    try:
        yield url
    finally:
        client.flushdb()


@pytest.fixture()
def redis_client(redis_url: str) -> Iterator["Redis"]:
    client = redis.Redis.from_url(redis_url)
    try:
        yield client
    finally:
        close = getattr(client, "close", None)
        if callable(close):  # pragma: no branch - best effort cleanup
            close()


@pytest.fixture()
def clean_state(redis_client: "Redis") -> Iterator[None]:
    redis_client.flushdb()
    try:
        yield
    finally:
        redis_client.flushdb()


@pytest.fixture()
def _clean_state(clean_state: None) -> Iterator[None]:
    """Alias fixture preserving legacy name used by shared-backend tests."""

    yield


def _unique_namespace(prefix: str = "suite") -> str:
    return f"{prefix}:{uuid4().hex}"


def _debug_context(redis_client: "Redis", namespace: str) -> str:
    keys = sorted(
        key.decode("utf-8") if isinstance(key, bytes) else str(key)
        for key in redis_client.keys("*")
    )
    payload = {
        "namespace": namespace,
        "redis_keys": keys,
        "timestamp": time.time(),
    }
    return json.dumps(payload, ensure_ascii=False)


def _metric_value(registry: CollectorRegistry, name: str, labels: dict[str, str] | None = None) -> float | None:
    return registry.get_sample_value(name, labels or {})


def _header_value(headers: dict[str, str], name: str) -> str | None:
    needle = name.lower()
    for key, value in headers.items():
        if key.lower() == needle:
            return value
    return None


def _post_with_retry(
    client: Any,
    *,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, object],
    max_attempts: int = 3,
    base_delay: float = 0.05,
) -> tuple[Any, float, int]:
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        response = client.post(url, headers=headers, json=json_body)
        duration = time.perf_counter() - start
        if response.status_code >= 500 and attempt < max_attempts:
            time.sleep(delay)
            delay = min(delay * 2, 0.2)
            continue
        return response, duration, attempt
    return response, duration, max_attempts
def _distributed_worker(args: tuple[str, str, str, dict[str, object], str]) -> tuple[int, dict[str, str]]:
    redis_url, namespace, token, payload, idem_key = args
    allocator = RedisCountingAllocator(redis_url, namespace)
    config = _config(
        redis_url,
        namespace=namespace,
        rate_limit_per_minute=600,
        rate_limit_burst=200,
        token=token,
    )
    registry = CollectorRegistry()
    app = create_app(allocator, config=config, registry=registry)
    transport = ClosingASGITransport(app=app)
    try:
        with httpx.Client(transport=transport, base_url="http://testserver") as client:
            headers = _auth_headers(token, **{"Idempotency-Key": idem_key})
            response, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
            return response.status_code, dict(response.headers)
    finally:
        transport.close()



def _build_app(
    config: HardenedAPIConfig,
    allocator: CountingAllocator,
    client_factory: Callable[[Any], Any],
) -> Any:
    registry = CollectorRegistry()
    app = create_app(allocator, config=config, registry=registry)
    client = client_factory(app)
    setattr(client, "app", app)
    return client


def _config(
    redis_url: str,
    *,
    namespace: str,
    rate_limit_per_minute: int = 1,
    rate_limit_burst: int = 1,
    token: str | None = None,
    compress_min_bytes: int | None = None,
    max_cache_bytes: int | None = None,
) -> HardenedAPIConfig:
    token_value = token or f"SharedToken{uuid4().hex[:16]}"
    config = HardenedAPIConfig(
        redis_url=redis_url,
        rate_limit_per_minute=rate_limit_per_minute,
        rate_limit_burst=rate_limit_burst,
        idempotency_ttl_seconds=3600,
        static_tokens={
            token_value: StaticCredential(
                token=token_value,
                scopes=frozenset({"alloc:write", "alloc:read"}),
                consumer_id="token:shared",
            )
        },
        metrics_token="metrics",
        required_scopes={
            "/allocations": {"alloc:write"},
            "/status": {"alloc:read"},
        },
    )
    config.redis_namespace = namespace
    config.instance_id = namespace
    if compress_min_bytes is not None:
        config.idempotency_compress_min_bytes = compress_min_bytes
    if max_cache_bytes is not None:
        config.idempotency_max_cache_bytes = max_cache_bytes
    return config


def _auth_headers(token: str, **extra: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    headers.update(extra)
    return headers


def _base_payload(mentor_id: int = 1) -> dict[str, object]:
    return {
        "student_id": "0012345679",
        "mentor_id": mentor_id,
        "reg_center": 1,
        "reg_status": 1,
        "gender": 0,
        "payload": {},
        "metadata": {},
    }


def _assert_duration(duration: float, debug: str) -> None:
    assert duration < 1.0, f"slow request {duration:.3f}s :: {debug}"


def test_rate_limit_shared_across_instances(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("rl-shared")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace)
    client_a = _build_app(config, allocator, httpx_client_factory)
    client_b = _build_app(config, allocator, httpx_client_factory)
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token)
    payload = _base_payload()

    first, duration_first, attempt_first = _post_with_retry(
        client_a, url="/allocations", headers=headers, json_body=payload
    )
    debug = _debug_context(redis_client, namespace)
    assert first.status_code == 200, debug
    _assert_duration(duration_first, debug)
    assert attempt_first == 1, debug

    second, duration_second, _ = _post_with_retry(
        client_b, url="/allocations", headers=headers, json_body=payload
    )
    debug = _debug_context(redis_client, namespace)
    assert second.status_code == 429, debug
    assert second.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED", debug
    _assert_duration(duration_second, debug)


def test_idempotency_shared_across_instances(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("idem-shared")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=60, rate_limit_burst=30)
    client_a = _build_app(config, allocator, httpx_client_factory)
    client_b = _build_app(config, allocator, httpx_client_factory)
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "SharedIdemKey123456"})
    payload = _base_payload(mentor_id=2)

    first, duration_first, _ = _post_with_retry(
        client_a, url="/allocations", headers=headers, json_body=payload
    )
    debug = _debug_context(redis_client, namespace)
    assert first.status_code == 200, debug
    _assert_duration(duration_first, debug)
    calls_after_first = len(allocator.calls)

    second, duration_second, _ = _post_with_retry(
        client_b, url="/allocations", headers=headers, json_body=payload
    )
    debug = _debug_context(redis_client, namespace)
    assert second.status_code == first.status_code, debug
    assert second.headers["X-Idempotent-Replay"] == "true", debug
    assert len(allocator.calls) == calls_after_first, debug
    _assert_duration(duration_second, debug)


def test_idempotent_storage_compression_metrics(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("idem-compress")
    allocator = CountingAllocator()
    allocator.message = "الف" * 4096
    config = _config(
        redis_url,
        namespace=namespace,
        rate_limit_per_minute=120,
        rate_limit_burst=60,
        compress_min_bytes=256,
    )
    client = _build_app(config, allocator, httpx_client_factory)
    registry = client.app.state.observability.registry  # type: ignore[attr-defined]
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "CompressKey123456"})
    payload = _base_payload(mentor_id=9)

    first, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    debug = _debug_context(redis_client, namespace)
    assert first.status_code == 200, debug

    second, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    assert second.status_code == 200, debug
    assert second.headers["X-Idempotent-Replay"] == "true", debug

    compressed_total = _metric_value(registry, "idemp_cache_compressed_total") or 0
    assert compressed_total >= 1, debug
    uncompressed_total = _metric_value(registry, "idemp_cache_uncompressed_total") or 0
    assert uncompressed_total == 0, debug
    stored_raw = _metric_value(registry, "idemp_cache_bytes_total", {"event": "store_raw"}) or 0
    stored_persisted = _metric_value(
        registry, "idemp_cache_bytes_total", {"event": "store_persisted"}
    ) or 0
    assert stored_raw > stored_persisted > 0, debug
    replay_bytes = _metric_value(registry, "idemp_cache_bytes_total", {"event": "replay"}) or 0
    assert replay_bytes == stored_raw, debug

    serialize_count = _metric_value(
        registry, "idemp_cache_serialize_seconds_count", {"mode": "compressed"}
    ) or 0
    replay_count = _metric_value(
        registry, "idemp_cache_replay_seconds_count", {"mode": "compressed"}
    ) or 0
    assert serialize_count == 1 and replay_count == 1, debug
    buffer_gauge = _metric_value(registry, "idemp_cache_buffer_bytes") or 0
    assert buffer_gauge == 0, debug


def test_idempotent_storage_uncompressed_metrics(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("idem-plain")
    allocator = CountingAllocator()
    allocator.message = "پیام"
    config = _config(
        redis_url,
        namespace=namespace,
        rate_limit_per_minute=120,
        rate_limit_burst=60,
        compress_min_bytes=4096,
    )
    client = _build_app(config, allocator, httpx_client_factory)
    registry = client.app.state.observability.registry  # type: ignore[attr-defined]
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "PlainKey12345678"})
    payload = _base_payload(mentor_id=10)

    first, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    debug = _debug_context(redis_client, namespace)
    assert first.status_code == 200, debug
    second, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    assert second.status_code == 200, debug
    assert second.headers["X-Idempotent-Replay"] == "true", debug

    uncompressed_total = _metric_value(registry, "idemp_cache_uncompressed_total") or 0
    assert uncompressed_total == 1, debug
    compressed_total = _metric_value(registry, "idemp_cache_compressed_total") or 0
    assert compressed_total == 0, debug
    stored_raw = _metric_value(registry, "idemp_cache_bytes_total", {"event": "store_raw"}) or 0
    stored_persisted = _metric_value(
        registry, "idemp_cache_bytes_total", {"event": "store_persisted"}
    ) or 0
    assert stored_raw == stored_persisted > 0, debug
    replay_bytes = _metric_value(registry, "idemp_cache_bytes_total", {"event": "replay"}) or 0
    assert replay_bytes == stored_raw, debug
    serialize_count = _metric_value(
        registry, "idemp_cache_serialize_seconds_count", {"mode": "plain"}
    ) or 0
    replay_count = _metric_value(
        registry, "idemp_cache_replay_seconds_count", {"mode": "plain"}
    ) or 0
    assert serialize_count == 1 and replay_count == 1, debug


def test_idempotent_storage_respects_max_cache_bytes(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("idem-max")
    allocator = CountingAllocator()
    allocator.message = "ب" * 2048
    config = _config(
        redis_url,
        namespace=namespace,
        rate_limit_per_minute=120,
        rate_limit_burst=60,
        max_cache_bytes=256,
    )
    client = _build_app(config, allocator, httpx_client_factory)
    registry = client.app.state.observability.registry  # type: ignore[attr-defined]
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "TooLargeKey123456"})
    payload = _base_payload(mentor_id=11)

    response, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    debug = _debug_context(redis_client, namespace)
    assert response.status_code == 503, debug
    assert response.headers.get("X-Degraded-Mode") == "true", debug
    assert response.json()["error"]["code"] == "DEGRADED_MODE", debug

    degraded_total = _metric_value(
        registry, "idempotency_degraded_total_total", {"reason": "cache-too-large"}
    )
    if degraded_total is None:
        degraded_total = _metric_value(
            registry, "idempotency_degraded_total", {"reason": "cache-too-large"}
        )
    assert degraded_total and degraded_total >= 1, debug

    replay_attempt, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    assert replay_attempt.status_code == response.status_code, debug
    assert replay_attempt.headers.get("X-Degraded-Mode") == "true", debug
    assert replay_attempt.json()["error"]["code"] == "DEGRADED_MODE", debug

    redis_keys = [key.decode("utf-8") if isinstance(key, bytes) else str(key) for key in redis_client.keys("*")]
    assert not any(key.startswith(f"idem:{namespace}") for key in redis_keys), debug
def test_redis_namespaces_are_isolated(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace_a = _unique_namespace("tenantA")
    namespace_b = _unique_namespace("tenantB")
    allocator_a = CountingAllocator()
    allocator_b = CountingAllocator()
    config_a = _config(redis_url, namespace=namespace_a, rate_limit_per_minute=60, rate_limit_burst=30)
    config_b = _config(redis_url, namespace=namespace_b, rate_limit_per_minute=60, rate_limit_burst=30)
    client_a = _build_app(config_a, allocator_a, httpx_client_factory)
    client_b = _build_app(config_b, allocator_b, httpx_client_factory)
    token_a = next(iter(config_a.static_tokens.keys()))
    token_b = next(iter(config_b.static_tokens.keys()))
    payload = _base_payload(mentor_id=3)

    first, _, _ = _post_with_retry(
        client_a, url="/allocations", headers=_auth_headers(token_a), json_body=payload
    )
    debug_a = _debug_context(redis_client, namespace_a)
    assert first.status_code == 200, debug_a

    parallel, _, _ = _post_with_retry(
        client_b, url="/allocations", headers=_auth_headers(token_b), json_body=payload
    )
    debug_b = _debug_context(redis_client, namespace_b)
    assert parallel.status_code == 200, debug_b

    idem_headers_a = _auth_headers(token_a, **{"Idempotency-Key": "NamespaceKey123456"})
    idem_headers_b = _auth_headers(token_b, **{"Idempotency-Key": "NamespaceKey123456"})
    replay_a, _, _ = _post_with_retry(
        client_a, url="/allocations", headers=idem_headers_a, json_body=payload
    )
    replay_b, _, _ = _post_with_retry(
        client_b, url="/allocations", headers=idem_headers_b, json_body=payload
    )
    debug = _debug_context(redis_client, f"{namespace_a}|{namespace_b}")
    assert replay_a.status_code == 200, debug
    assert replay_b.status_code == 200, debug
    assert replay_b.headers.get("X-Idempotent-Replay") != "true", debug
    assert len(allocator_b.calls) == 2, debug


def test_middleware_order_rate_limit_before_idempotency(
    redis_url: str,
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("order")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=60, rate_limit_burst=30)
    client = _build_app(config, allocator, httpx_client_factory)
    names = [middleware.cls.__name__ for middleware in client.app.user_middleware]
    debug = json.dumps({"middleware": names, "namespace": namespace}, ensure_ascii=False)
    assert "RateLimitMiddleware" in names and "IdempotencyMiddleware" in names, debug
    assert names.index("RateLimitMiddleware") < names.index("IdempotencyMiddleware"), debug


def test_concurrent_idempotent_requests(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("concurrent")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=600, rate_limit_burst=200)
    client = _build_app(config, allocator, httpx_client_factory)
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "ParallelKey123456"})
    payload = _base_payload(mentor_id=4)

    def _task() -> tuple[int, dict[str, str]]:
        response, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
        return response.status_code, dict(response.headers)

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: _task(), range(10)))

    statuses = [code for code, _ in results]
    headers_list = [hdrs for _, hdrs in results]
    debug = _debug_context(redis_client, namespace)
    assert statuses.count(200) == 10, debug
    replay_headers = [_header_value(hdr, "X-Idempotent-Replay") == "true" for hdr in headers_list]
    assert any(replay_headers), debug
    assert len(allocator.calls) == 1, debug


@pytest.mark.skipif(USE_REDIS_STUB, reason="Redis stub does not emulate transient script failures")
def test_transient_redis_failure_is_retried(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("retry")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=120, rate_limit_burst=60)
    client = _build_app(config, allocator, httpx_client_factory)
    backend = client.app.state.rate_limiter._backend  # type: ignore[attr-defined]
    original_script = getattr(backend, "_script", None)
    if original_script is None:
        pytest.skip("backend does not expose script callable")

    call_stats = {"total": 0, "failures": 0}

    async def flaky_script(*args, **kwargs):  # type: ignore[override]
        call_stats["total"] += 1
        if call_stats["failures"] == 0:
            call_stats["failures"] += 1
            raise RuntimeError("simulated transient failure")
        return await original_script(*args, **kwargs)

    backend._script = flaky_script  # type: ignore[assignment]
    try:
        token = next(iter(config.static_tokens.keys()))
        headers = _auth_headers(token)
        payload = _base_payload(mentor_id=5)
        response, duration, _ = _post_with_retry(
            client, url="/allocations", headers=headers, json_body=payload
        )
    finally:
        backend._script = original_script  # type: ignore[assignment]
    debug = _debug_context(redis_client, namespace)
    assert response.status_code == 200, debug
    _assert_duration(duration, debug)
    assert call_stats["failures"] == 1 and call_stats["total"] >= 2, debug


def test_dirty_state_is_cleaned(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("cleanup")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=60, rate_limit_burst=30)
    client = _build_app(config, allocator, httpx_client_factory)
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token)
    payload = _base_payload(mentor_id=6)
    response, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    debug = _debug_context(redis_client, namespace)
    assert response.status_code == 200, debug
    keys_after = redis_client.keys("*")
    assert keys_after, f"expected redis keys after request :: {debug}"
    redis_client.flushdb()
    assert not redis_client.keys("*"), f"redis should be empty after cleanup :: {debug}"

def test_idempotency_backend_degraded_mode(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("degraded")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=60, rate_limit_burst=30)
    client = _build_app(config, allocator, httpx_client_factory)
    store = client.app.state.idempotency_store  # type: ignore[attr-defined]
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "DegradedKey123456"})
    payload = _base_payload(mentor_id=7)

    if not hasattr(store, "_client"):
        pytest.skip("idempotency store does not expose redis client")

    original_get = store._client.get  # type: ignore[attr-defined]

    async def failing_get(*args, **kwargs):  # type: ignore[override]
        raise redis.exceptions.ConnectionError("simulated outage")

    store._client.get = failing_get  # type: ignore[attr-defined]
    try:
        response, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    finally:
        store._client.get = original_get  # type: ignore[attr-defined]
    debug = _debug_context(redis_client, namespace)
    assert response.status_code == 503, debug
    body = response.json()
    assert body["error"]["code"] == "DEGRADED_MODE", debug
    assert response.headers.get("X-Degraded-Mode") == "true", debug


@pytest.mark.skipif(USE_REDIS_STUB, reason="Redis stub does not support multi-process coordination")
def test_distributed_idempotency_across_processes(
    redis_url: str,
    redis_client: "Redis",
    _clean_state: None,
    httpx_client_factory,
) -> None:
    namespace = _unique_namespace("multiprocess")
    token = f"ProcToken{uuid4().hex[:16]}"
    idem_key = "ProcessKey12345678"
    payload = _base_payload(mentor_id=8)
    redis_client.delete(f"{namespace}:allocations")

    args = (redis_url, namespace, token, payload, idem_key)
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(_distributed_worker, [args] * 8)

    statuses = [code for code, _ in results]
    headers_list = [hdrs for _, hdrs in results]
    debug = _debug_context(redis_client, namespace)
    assert all(code == 200 for code in statuses), debug
    replay_count = sum(1 for hdrs in headers_list if hdrs.get("X-Idempotent-Replay") == "true")
    assert replay_count >= len(results) - 1, debug
    alloc_calls = int(redis_client.get(f"{namespace}:allocations") or 0)
    assert alloc_calls == 1, debug

    namespace = _unique_namespace("cleanup")
    allocator = CountingAllocator()
    config = _config(redis_url, namespace=namespace, rate_limit_per_minute=60, rate_limit_burst=30)
    client = _build_app(config, allocator, httpx_client_factory)
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token)
    payload = _base_payload(mentor_id=6)
    response, _, _ = _post_with_retry(client, url="/allocations", headers=headers, json_body=payload)
    debug = _debug_context(redis_client, namespace)
    assert response.status_code == 200, debug
    keys_after = redis_client.keys("*")
    assert keys_after, f"expected redis keys after request :: {debug}"
    redis_client.flushdb()
    assert not redis_client.keys("*"), f"redis should be empty after cleanup :: {debug}"
