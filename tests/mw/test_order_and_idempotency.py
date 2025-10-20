from __future__ import annotations

import asyncio

import pytest

from sma.phase6_import_to_sabt.app.middleware import IdempotencyMiddleware
from sma.phase6_import_to_sabt.app.utils import get_debug_context

pytestmark = pytest.mark.asyncio


async def request_with_retry(client, method: str, url: str, *, headers=None, json=None, attempts: int = 3):
    headers = headers or {}
    last = None
    for attempt in range(1, attempts + 1):
        response = await client.request(method, url, headers=headers, json=json)
        last = response
        if response.status_code < 500:
            return response
        await asyncio.sleep(0)
    return last


async def test_middleware_order_exact(async_client):
    headers = {
        "Authorization": "Bearer service-token",
        "Idempotency-Key": "abc123",
        "X-Client-ID": "tenant",
        "X-Request-ID": "rid-1",
    }
    response = await request_with_retry(async_client, "POST", "/api/jobs", headers=headers)
    body = response.json()
    assert body["middleware_chain"] == ["rate_limit", "idempotency", "auth"], get_debug_context(
        async_client.app, namespace="middleware-order", last_error=str(body)
    )


async def test_idempotency_window_24h():
    assert IdempotencyMiddleware.IDEMPOTENCY_TTL_SECONDS == 86400


async def test_get_fail_open_post_fail_closed(async_client):
    get_response = await async_client.get("/api/jobs", headers={"Authorization": "Bearer service-token"})
    assert get_response.status_code == 200, get_debug_context(
        async_client.app, namespace="jobs-get", last_error=get_response.text
    )
    post_response = await async_client.post(
        "/api/jobs",
        headers={"Authorization": "Bearer service-token", "X-Client-ID": "tenant"},
    )
    assert post_response.status_code == 400, get_debug_context(
        async_client.app, namespace="jobs-post", last_error=post_response.text
    )
    body = post_response.json()
    assert body["fa_error_envelope"]["code"] == "IDEMPOTENCY_KEY_REQUIRED", get_debug_context(
        async_client.app, namespace="jobs-post", last_error=str(body)
    )
