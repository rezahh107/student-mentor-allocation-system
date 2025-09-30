import asyncio

import httpx

from src.infrastructure.api.routes import create_app as create_infra_app
from tests.mw.test_middleware_order_all_apps import _build_phase6_app


def _send_request(app, method: str, path: str, **kwargs):
    async def _call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_call())


def test_metrics_requires_token_phase6(monkeypatch) -> None:
    app = _build_phase6_app(monkeypatch)
    response = _send_request(app, "GET", "/metrics")
    assert response.status_code in {401, 403}
    forbidden = _send_request(app, "GET", "/metrics", headers={"X-Metrics-Token": "wrong"})
    assert forbidden.status_code in {401, 403}
    ok = _send_request(app, "GET", "/metrics", headers={"X-Metrics-Token": "metrics-token"})
    assert ok.status_code == 200


def test_metrics_requires_token_infrastructure(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "infra-metrics")
    app = create_infra_app()
    response = _send_request(app, "GET", "/metrics")
    assert response.status_code == 401
    authorized = _send_request(app, "GET", "/metrics", headers={"X-Metrics-Token": "infra-metrics"})
    assert authorized.status_code == 200
