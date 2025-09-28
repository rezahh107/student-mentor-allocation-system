import asyncio
import uuid
from typing import Any

import httpx
import pytest
from prometheus_client import REGISTRY

from src.hardened_api.observability import metrics_registry_guard
from tests.hardened_api.conftest import build_counter_app, get_debug_context


def _headers(**extra: str) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "X-Request-ID": str(uuid.uuid4()),
    }
    headers.update(extra)
    return headers


class _SyncClient:
    def __init__(self, app) -> None:
        self._transport = httpx.ASGITransport(app=app)

    def request(self, method: str, url: str, **kwargs):
        async def _call():
            async with httpx.AsyncClient(transport=self._transport, base_url="http://testserver") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(_call())

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        asyncio.run(self._transport.aclose())


def _build_client() -> tuple[_SyncClient, Any]:
    app, redis_client = build_counter_app()
    return _SyncClient(app), redis_client


@pytest.fixture()
def client():
    with metrics_registry_guard():
        test_client, redis_client = _build_client()
        try:
            yield test_client, redis_client
        finally:
            asyncio.run(redis_client.flushdb())
            test_client.close()


def test_counter_allocate_success(client) -> None:
    test_client, _ = client
    payload = {"year": "1402", "gender": 1, "center": 1, "student_id": "student-001"}
    headers = _headers(**{"Idempotency-Key": "COUNTERTESTKEY001"})
    response = test_client.post("/counter/allocate", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["counter"].startswith("02")
    assert data["year_code"] == "02"
    cached = test_client.post("/counter/allocate", json=payload, headers=headers)
    assert cached.status_code == 200
    assert cached.json()["counter"] == data["counter"]


def test_counter_validation_error_is_persian(client) -> None:
    test_client, redis_client = client
    response = test_client.post(
        "/counter/allocate",
        json={"year": "abcd", "gender": 5, "center": 9, "student_id": ""},
        headers=_headers(),
    )
    body = response.json()
    assert response.status_code == 400, get_debug_context(redis_client=redis_client)
    assert body["ok"] is False
    assert body["code"] == "COUNTER_VALIDATION_ERROR"
    assert "درخواست نامعتبر" in body["message_fa"]


def test_counter_preview_success(client) -> None:
    test_client, _ = client
    response = test_client.get(
        "/counter/preview",
        params={"year": "1402", "gender": 0, "center": 1},
        headers=_headers(),
    )
    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["counter"].startswith("02")


def test_counter_metrics_increment(client) -> None:
    test_client, _ = client
    payload = {"year": "1402", "gender": 0, "center": 1, "student_id": "student-xyz"}
    headers = _headers(**{"Idempotency-Key": "COUNTERTESTKEY002"})
    test_client.post("/counter/allocate", json=payload, headers=headers)
    collected = {metric.name: metric for metric in REGISTRY.collect() if metric.name.startswith("counter_")}
    assert "counter_alloc" in collected
    alloc_samples = [s for s in collected["counter_alloc"].samples if s.name.endswith("_total")]
    assert any(sample.labels.get("status") == "success" and sample.value >= 1 for sample in alloc_samples)
