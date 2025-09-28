from __future__ import annotations

import asyncio
import uuid

import httpx

from src.hardened_api.observability import metrics_registry_guard
from tests.hardened_api.conftest import build_counter_app, get_debug_context


def test_persian_messages() -> None:
    async def _run() -> None:
        with metrics_registry_guard():
            app, redis = build_counter_app(namespace=f"test-{uuid.uuid4()}")
            transport = httpx.ASGITransport(app=app)
            try:
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                    response = await client.post(
                        "/counter/allocate",
                        json={"year": "", "gender": None, "center": "", "student_id": ""},
                        headers={
                            "Authorization": "Bearer TESTTOKEN1234567890",
                            "Content-Type": "application/json; charset=utf-8",
                            "Idempotency-Key": "invalid-payload-test",
                            "X-Request-ID": str(uuid.uuid4()),
                        },
                    )
                body = response.json()
                assert response.status_code == 400, get_debug_context(app, redis_client=redis)
                assert body["ok"] is False
                assert body["code"] == "COUNTER_VALIDATION_ERROR"
                assert body["message_fa"] == "درخواست نامعتبر است؛ سال/جنسیت/مرکز را بررسی کنید."
                assert "student" not in body
            finally:
                await redis.flushdb()
                await transport.aclose()

    asyncio.run(_run())
