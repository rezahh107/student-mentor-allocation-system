from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tooling.middleware_app import RedisNamespace, get_app, get_debug_context


@pytest.fixture()
def app_client(redis_client, redis_namespace):
    app = get_app(redis_client, redis_namespace, token="metrics-token")
    client = TestClient(app)
    yield client
    client.close()


def test_middleware_order_post_exact(app_client, redis_client, redis_namespace):
    payload = {
        "reg_center": 1,
        "reg_status": 3,
        "gender": 0,
        "mobile": "۰۹۱۲۳۴۵۶۷۸۹",
        "text_fields_name": "\u200cعلی",
        "national_id": "0061234567",
        "year": 2024,
        "counter": "123735678",
    }
    headers = {
        "Authorization": "Bearer metrics-token",
        "X-Request-ID": "req-1",
        "X-Idempotency-Key": uuid4().hex,
    }
    response = app_client.post("/submit", json=payload, headers=headers)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["middleware_order"] == ["rate-limit", "idempotency", "auth", "endpoint"]
    assert body["gender_prefix"] == "373"
    assert body["student_type"] == "special-2024"
    assert body["year_code"] == "24"

    # Ensure cached response served on repeat
    repeat = app_client.post("/submit", json=payload, headers=headers)
    assert repeat.status_code == 200
    assert repeat.json()["middleware_order"] == ["rate-limit", "idempotency", "auth", "endpoint"]

    redis_ns = RedisNamespace(redis_client, redis_namespace)
    ctx = get_debug_context(redis_ns)
    assert ctx["redis_keys"], ctx
    assert ctx["namespace"] == redis_namespace


def test_metrics_token_guard(app_client):
    resp = app_client.get("/metrics")
    assert resp.status_code == 403
    resp = app_client.get("/metrics", headers={"X-Metrics-Token": "metrics-token"})
    assert resp.status_code == 200


def test_persian_error_envelopes_deterministic(app_client):
    headers = {
        "Authorization": "Bearer metrics-token",
        "X-Request-ID": "req-error",
        "X-Idempotency-Key": uuid4().hex,
    }
    payload = {
        "reg_center": 9,
        "reg_status": 0,
        "gender": 0,
        "year": 2024,
    }
    first = app_client.post("/submit", json=payload, headers=headers)
    second = app_client.post("/submit", json=payload, headers=headers)
    assert first.status_code == 400
    assert second.status_code == 400
    assert first.json() == second.json() == {
        "error": "درخواست نامعتبر است؛ مقادیر reg_center یا reg_status خارج از دامنه است.",
    }
