from __future__ import annotations

import os

import pytest
from prometheus_client import CollectorRegistry

from src.api.api import HardenedAPIConfig, create_app
from src.api.middleware import StaticCredential
from src.phase3_allocation import AllocationRequest, AllocationResult


class FastAllocator:
    def allocate(self, request: AllocationRequest, dry_run: bool = False) -> AllocationResult:  # noqa: FBT001, FBT002
        return AllocationResult(
            allocation_id=1,
            allocation_code="23",
            year_code="23",
            mentor_id=request.mentor_id,
            status="OK",
            message="",
            error_code=None,
            idempotency_key="idem",
            outbox_event_id="evt",
            dry_run=False,
        )


@pytest.fixture(scope="module")
def _redis_url() -> str | None:
    try:  # pragma: no cover - optional extra guard
        import redis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/15")
        client = redis.Redis.from_url(url)
        client.ping()
        client.flushdb()
        return url
    except Exception:
        return None


def _exercise(client, headers, payload, iterations: int = 25) -> None:
    for _ in range(iterations):
        response = client.post("/allocations", headers=headers, json=payload)
        assert response.status_code == 200


def _budget_exceeded(registry) -> float:
    for metric in registry.collect():
        if metric.name == "http_latency_budget_exceeded_total":
            return sum(sample.value for sample in metric.samples)
    return 0.0


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _payload() -> dict[str, object]:
    return {
        "student_id": "0012345679",
        "mentor_id": 1,
        "reg_center": 1,
        "reg_status": 1,
        "gender": 0,
        "payload": {},
        "metadata": {},
    }


def test_latency_budget_not_exceeded_inmemory(httpx_client_factory) -> None:
    allocator = FastAllocator()
    registry = CollectorRegistry()
    token = "PerfToken1234567890"
    config = HardenedAPIConfig(
        rate_limit_per_minute=120,
        rate_limit_burst=60,
        latency_budget_ms=250,
        static_tokens={
            token: StaticCredential(token=token, scopes=frozenset({"alloc:write", "alloc:read"}), consumer_id="perf"),
        },
        required_scopes={
            "/allocations": {"alloc:write"},
            "/status": {"alloc:read"},
        },
    )
    app = create_app(allocator, config=config, registry=registry)
    client = httpx_client_factory(app)
    _exercise(client, _headers(token), _payload())
    assert _budget_exceeded(registry) == 0
    assert "loop" in app.state.runtime_extras


@pytest.mark.skipif("PYTEST_REDIS" not in os.environ, reason="Redis scenario disabled")
def test_latency_budget_not_exceeded_redis(httpx_client_factory, _redis_url) -> None:
    if _redis_url is None:
        pytest.skip("redis extra not installed or service unavailable")
    allocator = FastAllocator()
    registry = CollectorRegistry()
    token = "PerfToken1234567890"
    config = HardenedAPIConfig(
        redis_url=_redis_url,
        rate_limit_per_minute=120,
        rate_limit_burst=60,
        latency_budget_ms=250,
        static_tokens={
            token: StaticCredential(token=token, scopes=frozenset({"alloc:write", "alloc:read"}), consumer_id="perf"),
        },
        required_scopes={
            "/allocations": {"alloc:write"},
            "/status": {"alloc:read"},
        },
    )
    app = create_app(allocator, config=config, registry=registry)
    client = httpx_client_factory(app)
    _exercise(client, _headers(token), _payload())
    assert _budget_exceeded(registry) == 0
