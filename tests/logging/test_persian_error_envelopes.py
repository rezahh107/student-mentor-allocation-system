from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_persian_error_envelopes(async_client):
    missing_key = await async_client.post(
        "/api/jobs",
        headers={
            "Authorization": "Bearer service-token",
            "X-Client-ID": "tenant",
            "X-Request-ID": "persian-1",
        },
    )
    assert missing_key.status_code == 400
    envelope = missing_key.json()["fa_error_envelope"]
    assert envelope["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert envelope["message"] == "کلید ایدمپوتنسی الزامی است."

    unauthorized = await async_client.post(
        "/api/jobs",
        headers={
            "Authorization": "Bearer wrong-token",
            "Idempotency-Key": "persian-2",
            "X-Client-ID": "tenant",
            "X-Request-ID": "persian-2",
        },
    )
    assert unauthorized.status_code == 401
    unauthorized_envelope = unauthorized.json()["fa_error_envelope"]
    assert unauthorized_envelope["code"] == "UNAUTHORIZED"
    assert unauthorized_envelope["message"] == "دسترسی مجاز نیست."
    assert all(
        ord(ch) < 128 or 0x0600 <= ord(ch) <= 0x06FF
        for ch in unauthorized_envelope["message"]
        if not ch.isspace()
    )
