import asyncio

import httpx

from automation_audit.api import create_app


def test_protected_metrics(redis_client):
    app = create_app(redis_client=redis_client, auth_tokens=["token"])

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.get("/metrics", headers={"authorization": "Bearer token"})

    response = asyncio.run(call())
    assert response.status_code == 403
