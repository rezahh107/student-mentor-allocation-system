import asyncio

import httpx

from automation_audit.api import create_app


def test_bearer_and_ip(redis_client):
    app = create_app(
        redis_client=redis_client,
        auth_tokens=["token"],
        metrics_token="metrics-token",
        metrics_allowed_ips={"127.0.0.1"},
    )

    async def call(path: str, headers: dict[str, str] | None = None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.get(path, headers=headers or {})

    async def flow():
        ok = await call(
            "/metrics",
            headers={
                "authorization": "Bearer metrics-token",
                "x-forwarded-for": "127.0.0.1",
            },
        )
        return ok.status_code

    status_code = asyncio.run(flow())
    assert status_code == 200
