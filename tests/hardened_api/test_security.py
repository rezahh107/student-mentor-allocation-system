from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from tests.hardened_api.conftest import (
    assert_clean_final_state,
    get_debug_context,
    setup_test_data,
)
from src.hardened_api.observability import hash_national_id


def _default_headers(**extra):
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "X-Request-ID": str(uuid.uuid4()),
    }
    headers.update(extra)
    return headers


@pytest.mark.asyncio
async def test_missing_auth_returns_401(clean_state, client):
    payload = setup_test_data(unique_suffix="9")
    response = await client.post(
        "/allocations",
        json=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    await assert_clean_final_state(client)


@pytest.mark.parametrize("invalid_header", ["Bearer short", "Token invalid", "Bearer *************"])
@pytest.mark.asyncio
async def test_invalid_token(clean_state, client, invalid_header):
    payload = setup_test_data(unique_suffix="5")
    response = await client.post(
        "/allocations",
        json=payload,
        headers={"Authorization": invalid_header, "Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] in {"AUTH_REQUIRED", "INVALID_TOKEN"}
    await assert_clean_final_state(client)


def _make_jwt(payload: dict[str, Any], *, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=")
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    signing_input = b".".join([header_b64, payload_b64])
    import hmac
    import hashlib

    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return b".".join([header_b64, payload_b64, signature_b64]).decode()


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429(clean_state, client, redis_client):
    payload = setup_test_data(unique_suffix="3")
    results = []
    for _ in range(6):
        headers = _default_headers()
        response = await client.post("/allocations", json=payload, headers=headers)
        results.append(response)
    last = results[-1]
    assert last.status_code == 429, last.text
    assert last.headers["Retry-After"] == "1"
    assert last.headers["X-RateLimit-Remaining"] == "0"
    assert last.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    from src.hardened_api.observability import get_metric

    samples = get_metric("rate_limit_reject_total").collect()[0].samples
    assert any(sample.labels.get("route") == "/allocations" for sample in samples)
    await assert_clean_final_state(client)


@pytest.mark.asyncio
async def test_idempotency_reuses_first_result(clean_state, client, allocator):
    payload = setup_test_data(unique_suffix="1")
    headers = _default_headers(**{"Idempotency-Key": "IDEMPOTENCYKEY9876"})
    first = await client.post("/allocations", json=payload, headers=headers)
    second = await client.post("/allocations", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert len(allocator.calls) == 1
    await assert_clean_final_state(client)


@pytest.mark.asyncio
async def test_idempotency_conflict_returns_409(clean_state, client):
    payload = setup_test_data(unique_suffix="4")
    headers = _default_headers(**{"Idempotency-Key": "IDEMPOTENCYKEY5432"})
    first = await client.post("/allocations", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    payload["mentor_id"] = 222
    second = await client.post("/allocations", json=payload, headers=headers)
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "CONFLICT"
    await assert_clean_final_state(client)


@pytest.mark.asyncio
async def test_body_size_guard(clean_state, client):
    payload = {"student_id": "1" * 10, "mentor_id": 1, "reg_center": 0, "reg_status": 0, "gender": 0}
    oversized = json.dumps(payload).encode("utf-8") * 4000
    response = await client.post(
        "/allocations",
        content=oversized,
        headers={
            "Authorization": "Bearer TESTTOKEN1234567890",
            "Content-Type": "application/json; charset=utf-8",
            "Idempotency-Key": "SIZECHECKKEY12345",
        },
    )
    assert response.status_code == 413
    assert "حجم" in response.json()["error"]["message_fa"]
    await assert_clean_final_state(client)


@pytest.mark.asyncio
async def test_api_key_authentication(clean_state, client, auth_config):
    payload = setup_test_data(unique_suffix="6")
    api_key = "STATICKEY1234567890"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json; charset=utf-8",
        "Idempotency-Key": "APIKEYMODE123456",
    }
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    await assert_clean_final_state(client)


@pytest.mark.asyncio
async def test_expired_api_key_rejected(clean_state, client, auth_config):
    raw = "EXPIREDKEY000000"
    hashed = hash_national_id(raw, salt=auth_config.api_key_salt)
    from src.hardened_api.auth_repository import APIKeyRecord

    expired_record = APIKeyRecord(
        name="expired",
        key_hash=hashed,
        expires_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    )
    auth_config.api_key_repository.add(expired_record)
    headers = {
        "X-API-Key": raw,
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = setup_test_data(unique_suffix="2")
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_jwt_audience_validation(clean_state, client):
    payload = setup_test_data(unique_suffix="3")
    now = int(time.time())
    jwt_token = _make_jwt(
        {
            "sub": "user-1",
            "aud": "wrong",
            "iss": "issuer",
            "exp": now + 3600,
            "iat": now,
            "jti": "token-123",
        },
        secret="secret-key",
    )
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_jwt_revoked_denied(clean_state, client, auth_config, redis_client):
    now = int(time.time())
    payload = setup_test_data(unique_suffix="5")
    jwt_token = _make_jwt(
        {
            "sub": "user-3",
            "aud": "alloc",
            "iss": "issuer",
            "exp": now + 3600,
            "iat": now,
            "jti": "deny-1",
        },
        secret="secret-key",
    )
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    await auth_config.jwt_deny_list.revoke("deny-1", expires_in=10)
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_parallel_idempotent_requests(clean_state, client, allocator):
    payload = setup_test_data(unique_suffix="6")
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "Idempotency-Key": "PARALLELIDEMP0001",
    }
    tasks = [client.post("/allocations", json=payload, headers=headers) for _ in range(20)]
    results = await asyncio.gather(*tasks)
    assert sum(1 for r in results if r.status_code == 200) == 20
    assert len(allocator.calls) == 1


@pytest.mark.asyncio
async def test_rate_limit_dirty_state(clean_state, client, redis_client):
    payload = setup_test_data(unique_suffix="7")
    headers = _default_headers()
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 200
    # Simulate leftover bucket expiry
    redis_client._zsets.clear()  # noqa: SLF001
    response2 = await client.post("/allocations", json=payload, headers=headers)
    assert response2.status_code == 200


@pytest.mark.asyncio
async def test_idempotency_dirty_state(clean_state, client, redis_client, frozen_clock):
    payload = setup_test_data(unique_suffix="8")
    headers = _default_headers(**{"Idempotency-Key": "STALEIDEMP000001"})
    namespaces = client.app.state.middleware_state.namespaces  # type: ignore[attr-defined]
    key = namespaces.idempotency("STALEIDEMP000001")
    cached = json.dumps({"status": "completed", "body_hash": "stale", "response": {"status": "ok"}})
    await redis_client.set(key, cached, ex=1)
    await frozen_clock.advance(2)
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 200, response.text
