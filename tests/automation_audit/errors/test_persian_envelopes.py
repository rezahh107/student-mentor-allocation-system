import asyncio

import httpx

from automation_audit.api import create_app


def test_error_messages(redis_client):
    app = create_app(redis_client=redis_client, auth_tokens=["token"])

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.post("/audit", headers={"authorization": "Bearer token"})

    response = asyncio.run(call())
    assert response.status_code == 400
    assert "کلید تکرار" in response.json()["detail"]
