from __future__ import annotations

import os
from typing import Iterator

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from src.api.api import HardenedAPIConfig, create_app
from src.api.middleware import StaticCredential
from src.phase3_allocation import AllocationRequest, AllocationResult

try:  # pragma: no cover - optional dependency guard
    import redis
except Exception:  # pragma: no cover
    redis = None


class CountingAllocator:
    def __init__(self) -> None:
        self.calls: list[AllocationRequest] = []

    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        self.calls.append(request)
        return AllocationResult(
            allocation_id=len(self.calls),
            allocation_code="2301",
            year_code="23",
            mentor_id=request.mentor_id,
            status="OK",
            message="",
            error_code=None,
            idempotency_key=f"idem-{len(self.calls)}",
            outbox_event_id="evt",
            dry_run=False,
        )


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    if redis is None:
        pytest.skip("redis extra not installed")
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/15")
    client = redis.Redis.from_url(url)
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover - network issues
        pytest.skip(f"redis not available: {exc}")
    client.flushdb()
    yield url
    client.flushdb()


def _build_app(config: HardenedAPIConfig, allocator: CountingAllocator) -> TestClient:
    registry = CollectorRegistry()
    app = create_app(allocator, config=config, registry=registry)
    return TestClient(app, raise_server_exceptions=False)


def _config(redis_url: str) -> HardenedAPIConfig:
    token = "SharedToken1234567890"
    return HardenedAPIConfig(
        redis_url=redis_url,
        rate_limit_per_minute=1,
        rate_limit_burst=1,
        idempotency_ttl_seconds=3600,
        static_tokens={
            token: StaticCredential(token=token, scopes=frozenset({"alloc:write", "alloc:read"}), consumer_id="token:shared"),
        },
        metrics_token="metrics",
        required_scopes={
            "/allocations": {"alloc:write"},
            "/status": {"alloc:read"},
        },
    )


def _auth_headers(token: str, **extra: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    headers.update(extra)
    return headers


def test_rate_limit_shared_across_instances(redis_url: str) -> None:
    allocator = CountingAllocator()
    config = _config(redis_url)
    client_a = _build_app(config, allocator)
    client_b = _build_app(config, allocator)
    headers = _auth_headers(next(iter(config.static_tokens.keys())))
    payload = {
        "student_id": "0012345679",
        "mentor_id": 1,
        "reg_center": 1,
        "reg_status": 1,
        "gender": 0,
        "payload": {},
        "metadata": {},
    }
    first = client_a.post("/allocations", headers=headers, json=payload)
    assert first.status_code == 200
    second = client_b.post("/allocations", headers=headers, json=payload)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_idempotency_shared_across_instances(redis_url: str) -> None:
    allocator = CountingAllocator()
    config = _config(redis_url)
    client_a = _build_app(config, allocator)
    client_b = _build_app(config, allocator)
    token = next(iter(config.static_tokens.keys()))
    headers = _auth_headers(token, **{"Idempotency-Key": "SharedIdemKey123456"})
    payload = {
        "student_id": "0012345679",
        "mentor_id": 2,
        "reg_center": 1,
        "reg_status": 1,
        "gender": 0,
        "payload": {},
        "metadata": {},
    }
    first = client_a.post("/allocations", headers=headers, json=payload)
    assert first.status_code == 200
    calls_after_first = len(allocator.calls)
    second = client_b.post("/allocations", headers=headers, json=payload)
    assert second.status_code == first.status_code
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert len(allocator.calls) == calls_after_first


def test_redis_namespaces_are_isolated(redis_url: str) -> None:
    if redis is None:  # pragma: no cover - defensive
        pytest.skip("redis extra not installed")
    redis.Redis.from_url(redis_url).flushdb()
    allocator_a = CountingAllocator()
    allocator_b = CountingAllocator()
    config_a = _config(redis_url)
    config_a.redis_namespace = "tenantA"
    config_a.instance_id = "shared"
    config_b = _config(redis_url)
    config_b.redis_namespace = "tenantB"
    config_b.instance_id = "shared"
    client_a = _build_app(config_a, allocator_a)
    client_b = _build_app(config_b, allocator_b)
    token_a = next(iter(config_a.static_tokens.keys()))
    token_b = next(iter(config_b.static_tokens.keys()))
    payload = {
        "student_id": "0012345679",
        "mentor_id": 3,
        "reg_center": 1,
        "reg_status": 1,
        "gender": 0,
        "payload": {},
        "metadata": {},
    }
    first = client_a.post("/allocations", headers=_auth_headers(token_a), json=payload)
    assert first.status_code == 200
    parallel = client_b.post("/allocations", headers=_auth_headers(token_b), json=payload)
    assert parallel.status_code == 200
    idem_headers_a = _auth_headers(token_a, **{"Idempotency-Key": "NamespaceKey123456"})
    idem_headers_b = _auth_headers(token_b, **{"Idempotency-Key": "NamespaceKey123456"})
    replay_a = client_a.post("/allocations", headers=idem_headers_a, json=payload)
    replay_b = client_b.post("/allocations", headers=idem_headers_b, json=payload)
    assert replay_a.status_code == 200
    assert replay_b.status_code == 200
    assert replay_b.headers.get("X-Idempotent-Replay") != "true"
    assert len(allocator_b.calls) == 2
