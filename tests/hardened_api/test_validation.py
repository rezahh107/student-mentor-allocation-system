from __future__ import annotations

import json
import time
import uuid

import pytest

from tests.hardened_api.conftest import (
    assert_clean_final_state,
    get_debug_context,
    make_request_with_retry,
    setup_test_data,
    verify_middleware_order,
)


@pytest.mark.parametrize(
    "student_id",
    [
        "۱۲۳۴۵‌۶۷۸۹",  # Persian digits with zero-width non-joiner
        "0000000000",
    ],
)
@pytest.mark.asyncio
async def test_post_allocations_validation_errors(clean_state, client, redis_client, student_id):
    verify_middleware_order(client)
    payload = setup_test_data(unique_suffix="7")
    payload.update({"student_id": student_id, "phone": "09۱1۲2۳3۴4۵5۶6۷7"})
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "X-Request-ID": str(uuid.uuid4()),
        "Idempotency-Key": "IDEMPOTENCYKEY1234",
    }
    start = time.time()
    response = await make_request_with_retry(
        client,
        "post",
        "/allocations",
        json=payload,
        headers=headers,
    )
    duration = time.time() - start
    assert response.status_code == 422, (
        f"Unexpected status {response.status_code}: {response.text}\nContext: {get_debug_context(client, redis_client)}"
    )
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "پیام" not in json.dumps(body, ensure_ascii=False)
    assert body["error"]["message_fa"] == "اطلاعات ارسال‌شده نامعتبر است"
    assert duration < 1.0
    await assert_clean_final_state(client)


@pytest.mark.asyncio
async def test_post_allocations_content_type_guard(clean_state, client, redis_client):
    payload = setup_test_data(unique_suffix="8")
    response = await client.post(
        "/allocations",
        content=json.dumps(payload),
        headers={
            "Authorization": "Bearer TESTTOKEN1234567890",
            "Content-Type": "application/xml",
            "Idempotency-Key": "CTTYPEKEY123456",
        },
    )
    assert response.status_code == 415, response.text
    assert response.json()["error"]["message_fa"].startswith("نوع محتوا")
    await assert_clean_final_state(client)


@pytest.mark.parametrize("student_id", [None, "", "\u200c", "0"])
@pytest.mark.asyncio
async def test_post_allocations_empty_identifiers(clean_state, client, redis_client, student_id):
    payload = setup_test_data(unique_suffix="9")
    payload.update({"student_id": student_id})
    headers = {
        "Authorization": "Bearer TESTTOKEN1234567890",
        "Content-Type": "application/json; charset=utf-8",
        "Idempotency-Key": "EMPTYIDKEY123456",
    }
    response = await client.post("/allocations", json=payload, headers=headers)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    await assert_clean_final_state(client)
